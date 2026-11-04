"""
========================================
U.S. RHETORIC TRACKER (v1.4.0 -- Nov 1 2026; v1.0.0 May 2026)
========================================
v1.4.0 (Nov 1 2026, two days before the midterms):
  * GOVERNANCE BLOCK + SIGNAL for the GPI governance axis (same contract as
    Israel's government_formation): election phase from
    us_government_composition, chamber control, acting officials, and an
    ELECTION-ADMINISTRATION lane (certification refusals, recounts,
    concession refusals, threats to election officials, federal agents at
    polling places, results-driven mobilization). Institutional EVENTS only;
    corroboration (2+ reports, 2+ sources) required above L2; L5 is never
    asserted from keywords (L5 assertion rule).
  * us_civil_mobilization: a TWO-SIDED civil-society actor (Rachel, Nov 1):
    left-leaning (No Kings, Indivisible, MoveOn, Lincoln Project) and
    right-leaning (Turning Point Action/USA, MAGA Inc., Heritage Action,
    Americans for Prosperity), counted per side. Before Election Day it is
    campaign context; after, results-driven mobilization is the signal.
    "lincoln project" / "never trump" removed from the Congress-opposition
    actor: outside groups inflated a CONGRESS score, and the majority side
    had no equivalent. "never trump" is a label, not an organisation.
  * Canonical signal fields (level, priority, theatre, pressure_type) on
    every top_signal -- the WHA BLUF defaulted all US signals to priority 5.
  * NewsAPI through newsapi_gateway (old key deleted 18 Oct; this tracker
    had been reporting 'not_configured' since). GDELT None guard.
  * Stale facts: Powell (Fed chair is Warsh since May 2026), Noem (DHS is
    Mullin), departed spokespeople/governors, the DHS "shutdown" note,
    generic MOU tripwires anchored to Iran. us_taco_index_v0 placeholder
    removed from the fingerprint.
  * Absence-honest: a scan with almost no articles reports NOT SENSED,
    never "Quiet Week".
Multi-actor rhetoric monitoring for the United States — the only tracker
in the Asifah corpus where every other tracker reads from us, and we read
from every other tracker.

CALIBRATION PHILOSOPHY (per Rachel + Peter, May 2026):
  Score reflects RHETORIC VOLATILITY and CROSS-SPECTRUM FRACTURE, not
  aggression. The US is generally on the upper edge of stable. View from
  Foggy Bottom feels more volatile than view from Iowa, and the score
  reflects the median American experience, not DC pundit experience.

  0-25:  STABLE      Coherent posture, low partisan divergence, allies aligned
  26-50: ACTIVE      Assertive posture, normal disagreement, manageable
  51-75: VOLATILE    Sharp divergence, allies distancing, branches contradicting
  76-100: CRISIS     Branches openly fighting, allies breaking publicly,
                     multiple foreign actors targeting US directly

ACTORS (9):

  EXECUTIVE LAYER (3)
  ─────────────────────────
  us_executive          Trump + WH press + cabinet (weight 1.2 — primary)
  us_state_dept         Diplomatic posture (weight 1.0)
  us_defense            Pentagon / CENTCOM / SOCOM / NORTHCOM (weight 1.0)

  LEGISLATIVE LAYER (2)
  ─────────────────────────
  us_congress_majority    House R + Senate leadership (weight 0.95)
  us_congress_opposition  Dem leadership + opposition voices (weight 0.95)

  INSTITUTIONAL LAYER (4)
  ─────────────────────────
  us_judicial           SCOTUS + DOJ + courts (weight 1.05)
  us_dhs_ice            DHS + ICE + immigration enforcement (weight 1.1) ⭐
  us_federal_reserve    Powell + FOMC statements (weight 0.85)
  us_states             Governors pushing back on federal posture (weight 0.85)

CROSS-THEATER ARCHITECTURE:
  - READS fingerprints from: ALL trackers (ME 6, Asia 4, Europe 4, WHA 6+)
  - WRITES fingerprint: us_active, us_outbound_targets[], us_executive_volatility,
                        us_dhs_enforcement_active, us_branch_divergence_score,
                        us_domestic_fracture_score, us_taco_index_v0 (placeholder)

REDIS KEYS WRITTEN:
  rhetoric:us:latest         (current scan results, no TTL)
  rhetoric:us:summary        (compact summary for dashboards)
  rhetoric:us:history        (last 12 weeks, snapshot index pattern)
  fingerprint:us:current     (cross-theater fingerprint contract)

ENDPOINTS REGISTERED:
  GET /api/rhetoric/us
  GET /api/rhetoric/us/debug
"""

import os
import re
import json
import time
import threading
import requests
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta


# ════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════

print("[US Rhetoric] Module loading...")

SCAN_INTERVAL_HOURS    = 12
INITIAL_BOOT_DELAY_SEC = 90
GDELT_TIMEOUT_SEC      = 8
RSS_TIMEOUT_SEC        = 12
NEWSAPI_TIMEOUT_SEC    = 10
DEFAULT_MAX_ARTICLES   = 25

# Defensive: support both env var naming conventions used across Asifah trackers.
# Peru/Chile use UPSTASH_REDIS_URL; some docs reference UPSTASH_REDIS_REST_URL.
# Try both so the tracker works regardless of which one is configured on Render.
UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_URL', '') or os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '') or os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
NEWSAPI_KEY   = os.environ.get('NEWSAPI_KEY', '')   # legacy; deleted from Render 18 Oct 2026
TRACKER_VERSION = '1.5.1'   # Nov 4 2026 pm: So What leads with the election result in the post-election window; RSS with some failed feeds reads 'partial', not 'http error' | 1.5.0 Nov 4 2026: results phase -- hedged mentions skipped, rung-2 needs corroboration, acceptance/concession lane, reported chamber control, plain headline | 1.4.1 Nov 1: pre-election gating, commentary + past-cycle guards
# v1.4.0: NewsAPI through the shared gateway (budget, cache, stand-down).
try:
    from newsapi_gateway import newsapi_fetch_probed as _newsapi_gw
except Exception:
    _newsapi_gw = None
# v1.4.0: government composition + election phase (governance block).
try:
    from us_government_composition import get_government_composition as _get_govt
except Exception:
    _get_govt = None
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY', '')

REDIS_AVAILABLE  = bool(UPSTASH_URL and UPSTASH_TOKEN)
NEWSAPI_AVAILABLE = bool(NEWSAPI_KEY) or (_newsapi_gw is not None)
BRAVE_AVAILABLE  = bool(BRAVE_API_KEY)

# Diagnostic logging — show which env vars resolved at module load
print(f"[US Rhetoric] Redis available: {REDIS_AVAILABLE} (URL len={len(UPSTASH_URL)}, TOKEN len={len(UPSTASH_TOKEN)})")
print(f"[US Rhetoric] NewsAPI available: {NEWSAPI_AVAILABLE} (key len={len(NEWSAPI_KEY)})")
print(f"[US Rhetoric] Brave available: {BRAVE_AVAILABLE} (key len={len(BRAVE_API_KEY)})")

# Phase 5b (May 15, 2026) — Jawboning primitive wire-in.
# GREENFIELD: the US tracker has no inline Trump signal computation, so this
# is a direct write-path. Every scan POSTs actor_results to ME's catalog-based
# detector; the detector evaluates all 11 Trump command signatures and writes
# cross-theater fingerprints (jawboning:command:us:on_china, :on_iran, etc.)
# with 24h TTL. Cross-theater consumers (Iran/China/Cuba/Russia trackers) read
# those fingerprints directly from Redis — they never call the detector.
# Failure mode: if proxy unreachable, jawboning fingerprints don't write for
# this scan, but the US scan still completes normally. Bounded by threaded
# timeout in run_us_rhetoric_scan() Phase 5.5 block.
try:
    from jawboning_proxy_wha import detect_jawboning_via_proxy
    JAWBONING_PRIMITIVE_AVAILABLE = True
    print("[US Rhetoric] ✅ Jawboning primitive available (Phase 5b — Trump wire-in)")
except ImportError:
    JAWBONING_PRIMITIVE_AVAILABLE = False
    print("[US Rhetoric] ⚠️ Jawboning primitive not importable — signatures will not fire this scan")

# Show first 30 chars of URL so we can verify we got the right one (without
# leaking the token). This helps catch env var typos.
if UPSTASH_URL:
    print(f"[US Rhetoric] Redis URL prefix: {UPSTASH_URL[:30]}...")
if NEWSAPI_KEY:
    print(f"[US Rhetoric] NewsAPI key prefix: {NEWSAPI_KEY[:8]}... (suffix: ...{NEWSAPI_KEY[-4:]})")

# ── Social signal modules (graceful degradation) ──
try:
    from bluesky_signals_wha import fetch_bluesky_for_target
    BLUESKY_AVAILABLE = True
    print("[US Rhetoric] ✅ Bluesky module loaded")
except ImportError as e:
    BLUESKY_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Bluesky unavailable ({e})")

try:
    from telegram_signals_wha import fetch_telegram_signals_us
    TELEGRAM_AVAILABLE = True
    print("[US Rhetoric] ✅ Telegram module loaded")
except ImportError as e:
    TELEGRAM_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Telegram unavailable ({e})")

try:
    from reddit_signals_us import fetch_reddit_signals_us
    REDDIT_AVAILABLE = True
    print("[US Rhetoric] ✅ Reddit module loaded")
except ImportError as e:
    REDDIT_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Reddit unavailable ({e})")

try:
    from us_signal_interpreter import (
        compute_top_signals,
        compute_so_what_factor,
        compute_branch_divergence_score,
        compute_domestic_fracture_score,
        compute_capability_rhetoric_gap,
    )
    INTERPRETER_AVAILABLE = True
    print("[US Rhetoric] ✅ Signal interpreter loaded")
except ImportError as e:
    INTERPRETER_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Signal interpreter unavailable ({e})")


# ════════════════════════════════════════════════════════════════════
# THE 9-ACTOR MATRIX
# ════════════════════════════════════════════════════════════════════
# Each actor entry contains:
#   name, flag, icon, color, role, description (display)
#   keywords (case-insensitive substring matches in title+description)
#   baseline_statements_per_week (calibration baseline)
#   tripwires (high-severity signal phrases that auto-elevate the actor's tier)
#   weight (signal contribution multiplier)
#   layer (executive | legislative | institutional)
# ════════════════════════════════════════════════════════════════════

ACTORS = {

    # ════════════════════════════════════════════════════════════════
    # EXECUTIVE LAYER (3 actors)
    # ════════════════════════════════════════════════════════════════

    'us_executive': {
        'name':  'U.S. Executive Branch',
        'flag':  '🇺🇸',
        'icon':  '🏛️',
        'color': '#dc2626',
        'role':  'White House / Trump / Cabinet -- Primary Political Rhetoric',
        'layer': 'executive',
        'weight': 1.2,
        'description': (
            'Presidential and White House rhetoric. Highest weight because executive '
            'rhetoric drives headline cycles, market moves, and cross-theater rhetoric. '
            'Watch for: Truth Social posts, WH press briefings, cabinet statements, '
            'EO announcements, Rose Garden speeches.'
        ),
        # ════════════════════════════════════════════════════════════
        # KEYWORD DESIGN (rewritten Sep 7 2026)
        # ════════════════════════════════════════════════════════════
        # This net answers ONE question: DID THE EXECUTIVE SPEAK.
        # It does NOT answer what about. Topic detection belongs to the
        # jawboning catalog (trump_on_iran, trump_on_china, ...), which
        # reads this actor's articles and applies its own trigger phrases.
        #
        # Sep 7 2026 diagnosis: this actor matched 4 articles out of 664
        # and scored L0 on a day the US was striking Iranian tankers in
        # Hormuz. Cause: the net had 'trump statement' and 'trump announces'
        # but not 'trump said', which is how wire copy actually attributes
        # presidential speech. It also carried roughly 30 frozen event
        # phrases from specific May and June cycles, which made coverage
        # hostage to whatever was in the news when the list was last edited.
        #
        # RULE GOING FORWARD: add attribution forms here. Add topics to the
        # jawboning catalog. If you are adding a phrase that names a
        # specific deal, week, or document, it belongs in the catalog.
        # ════════════════════════════════════════════════════════════
        'keywords': [
            # ── Attribution: how wire copy reports presidential speech ──
            'trump said', 'trump says', 'trump told', 'trump wrote',
            'trump posted', 'trump vows', 'trump vowed',
            'trump warns', 'trump warned', 'trump threatens', 'trump threatened',
            'trump orders', 'trump ordered', 'trump authorized', 'trump authorised',
            'trump announces', 'trump announced', 'trump declares', 'trump declared',
            'trump calls for', 'trump called for', 'trump demands', 'trump demanded',
            'trump pledges', 'trump pledged', 'trump insists', 'trump claims',
            'trump confirms', 'trump confirmed', 'trump denies', 'trump denied',
            'trump statement', 'trump remarks', 'trump speech', 'trump rally',
            'trump interview', 'trump press conference',
            # ── Office and title forms ──
            'president trump', 'trump administration', 'potus',
            'commander in chief', 'oval office', 'air force one',
            'rose garden', 'mar-a-lago statement',
            # ── Truth Social (the primary channel) ──
            'trump truth social', 'trump truth post', 'truth social post',
            'truth social', 'posted on truth social',
            # ── White House as institution ──
            'white house said', 'white house says', 'white house statement',
            'white house announces', 'white house announced',
            'white house official', 'white house officials',
            'white house press secretary', 'white house spokesperson',
            'wh press secretary', 'wh briefing room', 'press briefing',
            'administration official', 'senior administration official',
            'executive order signed', 'president signs', 'president announces',
            'cabinet meeting', 'cabinet statement',
            # ── Cabinet principals, attribution forms ──
            'rubio said', 'rubio statement', 'secretary rubio',
            'hegseth said', 'hegseth statement', 'secretary hegseth',
            # v1.4.0: DHS Mullin (Mar 2026); AG Blanche (sworn in Aug 10 2026);
            # Labor Sonderling (Sep 30 2026); acting DNI Pulte (Jun 2 2026).
            'mullin said', 'secretary mullin', 'dhs secretary said',
            'blanche said', 'attorney general blanche', 'ag blanche',
            'sonderling said', 'labor secretary sonderling',
            'pulte said', 'acting dni', 'acting director of national intelligence',
            'bessent said', 'bessent treasury', 'lutnick commerce',
            'kennedy hhs statement',
            # ── Frozen event vocabulary (May-Jun 2026 cycles) ──
            # Kept deliberately: if these phrases recur they are
            # high-precision signals. But they are HISTORICAL, not general
            # coverage. Do not add more of this shape. Topics go in the
            # jawboning catalog.
            'trump iran deal', 'trump iran agreement',
            'trump iran largely negotiated', 'trump largely negotiated',
            'trump iran final details', 'trump iran peace deal',
            'trump iran peace agreement', 'trump iran hormuz reopen',
            'trump iran hormuz', 'trump iran framework',
            'trump iran nuclear deal', 'trump iran witkoff',
            'trump iran pakistan', 'trump iran munir',
            'trump credits pakistan iran', 'trump praises pakistan iran',
            'trump iran encouraging progress', 'trump iran 14-clause',
            'trump iran mou', 'trump iran memorandum',
            'truth social iran deal', 'truth social iran',
            'hormuz strait open', 'strait is open', 'reopen the strait',
            'deal signed tomorrow', 'deal is scheduled',
            'trump hormuz open', 'trump iran deal signed', 'no nuclear weapon',
            'truth social hormuz', 'trump iran cessation', 'trump lifts blockade',
            # ── Spanish (for ES tab) ──
            'declaración trump', 'casa blanca declara', 'comunicado casa blanca',
            'trump dijo', 'trump advirtió',
        ],
        'tripwires': [
            'trump invokes insurrection act', 'trump declares national emergency',
            'trump threatens military', 'trump fires cabinet',
            'wh threatens', 'trump withdraws', 'trump terminates',
            'trump declares war', 'trump activates national guard',
        ],
        # CALIBRATION WARNING (Sep 7 2026): this baseline of 50 was set
        # against the OLD narrow net that matched ~4 articles per scan.
        # With the net above it will match far more and the score will
        # jump. That jump is the fix working, not a new signal. Re-derive
        # this number from an observed statement_count after a clean scan.
        'baseline_statements_per_week': 50,
    },

    'us_state_dept': {
        'name':  'U.S. State Department',
        'flag':  '🇺🇸',
        'icon':  '🌐',
        'color': '#2563eb',
        'role':  'Diplomatic Posture / Foggy Bottom',
        'layer': 'executive',
        'weight': 1.0,
        'description': (
            'State Department official statements, briefings, ambassador postings, '
            'and treaty/agreement language. Indicator of allied alignment vs friction. '
            'Watch for: Spokesperson briefings, public statements on foreign policy, '
            'ambassador recall language, treaty withdrawal signals. v1.5.0 (May 24, '
            '2026): expanded with Iran-deal-specific keywords (Witkoff envoy, '
            'Pakistan/Munir mediation, MOU framework, Hormuz reopening).'
        ),
        'keywords': [
            'state department briefing', 'state department spokesperson',
            'state department announces', 'state department condemns',
            'state department statement', 'foggy bottom',
            'us ambassador', 'us embassy', 'us chief of mission',
            'us recalls ambassador', 'us expels diplomat',
            'state dept human rights', 'state dept democracy',
            'us treaty', 'us withdraws from treaty', 'us suspends agreement',
            'us sanctions waiver', 'us travel advisory',
            'briefing at state department',   # v1.4.0: named past spokespeople removed
            # ── v1.5.0 (May 24, 2026) — Iran deal envoy diplomacy ──
            'witkoff envoy', 'steve witkoff', 'witkoff islamabad',
            'witkoff tehran', 'witkoff iran shuttle', 'witkoff mediation',
            'us envoy iran', 'us special envoy iran',
            'us iran deal', 'us iran agreement', 'us iran framework',
            'us iran mou', 'us iran memorandum',
            'us iran 14-clause', 'us iran 14 clause',
            'us formal response iran', 'us responds iran proposal',
            'us iran proposal response', 'us iran final understanding',
            'us iran hormuz reopen', 'us iran hormuz agreement',
            'us iran heu surrender', 'us iran natanz dismantle',
            'us iran fordow dismantle', 'us iran isfahan dismantle',
            'us iran nuclear sites dismantle',
            'us iran largely negotiated', 'us iran encouraging progress',
            'us iran rapprochement', 'us iran trend rapprochement',
            'state department iran deal', 'state department iran envoy',
            'state department iran framework',
            'state department pakistan mediation',
            'us welcomes pakistan iran', 'us pakistan iran mediation',
            'us munir iran', 'us field marshal munir',
            'us back-channel iran', 'us backchannel iran',
            # ── v1.6.0 Jun 14 2026 — Islamabad MOU signing cycle (instrument/mediation) ──
            'islamabad memorandum', 'islamabad mou', 'mou signing', 'mou draft',
            'memorandum of understanding', 'cessation of hostilities',
            'qatari negotiators', 'qatar negotiators', 'qatari mediation',
            'qatari delegation', 'qatar mediates iran',
            'dilute highly enriched', 'dilute heu', 'uranium dilution',
            'no new enrichment', 'enrich no new uranium', 'enrichment freeze',
            'frozen assets', 'iran frozen assets', 'release frozen assets',
            'assets unfrozen', 'waive oil sanctions', 'oil sanctions waived',
            'lifts naval blockade', 'naval blockade lifted', 'lift the blockade',
            'blockade lifted', '60-day framework', '60-day period',
            'war ending agreement', 'war-ending agreement', 'ending the iran war',
            # Spanish
            'departamento de estado', 'secretario de estado',
        ],
        'tripwires': [
            'us recalls ambassador', 'us closes embassy', 'us expels diplomat',
            'us breaks diplomatic relations', 'us terminates treaty',
            'state dept resignation', 'mass resignation state dept',
            # ── v1.5.0 May 24 2026 — DIPLOMATIC BREAKTHROUGH TRIPWIRES (positive) ──
            'iran us deal announced', 'iran us peace deal signed',
            'iran us framework signed', 'iran nuclear deal signed',
            'iran ceasefire deal signed', 'iran hormuz reopening agreement',
            # ── v1.6.0 Jun 14 2026 — Islamabad MOU milestones ──
            # v1.4.0: anchored to Iran -- bare 'mou signed' fired on any MOU.
            'iran mou signed', 'iran memorandum signed', 'cessation of hostilities signed',
            'hormuz open to all', 'naval blockade lifted', 'iran war ends',
        ],
        'baseline_statements_per_week': 30,
    },

    'us_defense': {
        'name':  'U.S. Department of Defense',
        'flag':  '🇺🇸',
        'icon':  '🎖️',
        'color': '#166534',
        'role':  'Pentagon / Combatant Commands / Military Posture Rhetoric',
        'layer': 'executive',
        'weight': 1.0,
        'description': (
            'Pentagon, CENTCOM, NORTHCOM, SOCOM, INDOPACOM rhetoric and posture '
            'announcements. Distinct from Asifah Military Tracker (which counts ships) -- '
            'this captures the LANGUAGE of force projection. Watch for: deployment '
            'announcements, posture changes, exercises, NDAA disputes, Joint Chiefs '
            'public statements.'
        ),
        # Same rewrite as us_executive (Sep 7 2026): the old net was built
        # from announcement verbs only ('pentagon announces') and matched 2
        # articles out of 664 during active CENTCOM operations. Attribution
        # forms added below. Topic detection stays in the jawboning catalog.
        'keywords': [
            # ── Pentagon attribution ──
            'pentagon said', 'pentagon says', 'pentagon statement',
            'pentagon announces', 'pentagon announced', 'pentagon confirms',
            'pentagon confirmed', 'pentagon spokesman', 'pentagon spokesperson',
            'pentagon press secretary', 'pentagon press briefing',
            'defense department', 'department of defense', 'dod said',
            'war department', 'defense official', 'defense officials',
            'senior defense official', 'us military official',
            'us officials said', 'military spokesman',
            # ── Combatant commands ──
            'centcom', 'centcom said', 'centcom announces', 'centcom statement',
            'us central command', 'central command said',
            'northcom', 'southcom', 'socom', 'indopacom', 'eucom', 'africom',
            'combatant command', 'fifth fleet', 'sixth fleet', 'seventh fleet',
            # ── Secretary and Joint Chiefs ──
            'sec def hegseth', 'secretary hegseth', 'defense secretary',
            'defense secretary said', 'secretary of defense said',
            'joint chiefs', 'chairman joint chiefs',
            'chairman of the joint chiefs', 'joint staff',
            # ── Posture and force language ──
            'us military deployment', 'us troops deploy', 'us forces deploy',
            'us forces struck', 'us forces conducted', 'us military struck',
            'carrier strike group', 'aircraft carrier deploys',
            'us military exercise', 'us forces exercise',
            'us troop posture', 'us force posture review',
            'force protection', 'threat condition', 'ordered departure',
            # ── Legislative interface (first thread of the cost ledger) ──
            'ndaa', 'defense authorization', 'defense appropriations',
            'unfunded priorities', 'supplemental request',
        ],
        'tripwires': [
            'us troops to', 'carrier deploys', 'pentagon escalates',
            'centcom escalates', 'us forces engage',
            'pentagon issues warning', 'us military strike',
            'us forces respond',
        ],
        # Same calibration warning as us_executive. Re-derive after a clean scan.
        'baseline_statements_per_week': 25,
    },

    # ════════════════════════════════════════════════════════════════
    # LEGISLATIVE LAYER (2 actors)
    # ════════════════════════════════════════════════════════════════

    'us_congress_majority': {
        'name':  'Congress — Majority',
        'flag':  '🇺🇸',
        'icon':  '🏛️',
        'color': '#b91c1c',
        # v1.4.0: ROLE-labelled. Party control as of Nov 2026 is R in both
        # chambers; after Jan 3 2027 the keyword lists below must follow the
        # new majority (Phase 2: role-coded lists from the composition module).
        'role':  'Majority-party leadership, House + Senate (Republican as of Nov 2026)',
        'layer': 'legislative',
        'weight': 0.95,
        'description': (
            'House Republican majority + Senate leadership rhetoric. Captures legislative '
            'agenda statements, leadership press conferences, committee chair statements, '
            'and majority-coordinated messaging.'
        ),
        'keywords': [
            'speaker johnson', 'speaker mike johnson', 'house speaker',
            'house republican', 'house gop', 'gop leadership',
            'senate majority leader', 'senate leadership',
            'senator thune', 'leader thune', 'senate gop',
            'house majority leader', 'majority whip',
            'committee chair', 'house chair', 'senate chair',
            'gop press conference', 'republican leadership',
            'house republicans pass', 'gop bill',
            'congressional republicans', 'gop senators',
            # Specific committee chairs
            'jim jordan', 'mike rogers armed services',   # v1.4.0: departed member removed
        ],
        'tripwires': [
            'house gop blocks', 'house impeaches', 'gop impeachment',
            'gop senators break', 'gop revolt',
            'speaker resigns', 'speaker ousted',
            'gop leadership crisis',
        ],
        'baseline_statements_per_week': 35,
    },

    'us_congress_opposition': {
        'name':  'Congress — Opposition',
        'flag':  '🇺🇸',
        'icon':  '🏛️',
        'color': '#1d4ed8',
        'role':  'Minority-party leadership, House + Senate (Democratic as of Nov 2026)',
        'layer': 'legislative',
        'weight': 0.95,
        'description': (
            'House Democratic minority + Senate Democrats + opposition voices. Critical '
            'for measuring cross-spectrum rhetoric divergence. Captures opposition press '
            'conferences, ranking member statements, dissent on EOs, oversight rhetoric.'
        ),
        'keywords': [
            'minority leader jeffries', 'hakeem jeffries', 'rep jeffries',
            'house democrat', 'house dems', 'house minority',
            'senate minority leader', 'senate democrats',
            'schumer statement', 'senator schumer',
            'congressional democrats', 'dem leadership',
            'house dems oppose', 'dems block', 'dems push back',
            'ranking member', 'oversight democrats',
            'progressive caucus', 'house progressives',
            'rep aoc', 'aoc statement', 'rep ocasio-cortez',
            'sen warren', 'sen sanders', 'sen warnock',
            'sen booker', 'sen padilla', 'sen ossoff',
            # v1.4.0: outside groups moved to us_civil_mobilization (two-sided).
        ],
        'tripwires': [
            'dems file impeachment', 'dems walk out',
            'mass dem resignation', 'opposition demands resignation',
            'dems file articles', 'house dems sue',
            'dems block confirmation',
        ],
        'baseline_statements_per_week': 35,
    },

    # ════════════════════════════════════════════════════════════════
    # INSTITUTIONAL LAYER (4 actors)
    # ════════════════════════════════════════════════════════════════

    'us_judicial': {
        'name':  'U.S. Judicial Branch',
        'flag':  '🇺🇸',
        'icon':  '⚖️',
        'color': '#7c2d12',
        'role':  'SCOTUS / Federal Courts / DOJ Rhetoric',
        'layer': 'institutional',
        'weight': 1.05,
        'description': (
            'SCOTUS opinions, federal court rulings on EOs, DOJ statements, and judicial '
            'rhetoric. Critical for institutional pushback signal. Watch for: SCOTUS '
            'rulings, lower court injunctions on EOs, DOJ press conferences, recusal/'
            'resignation language, contempt findings.'
        ),
        'keywords': [
            'supreme court ruling', 'scotus ruling', 'scotus decision',
            'supreme court strikes down', 'supreme court upholds',
            'chief justice roberts', 'justice sotomayor', 'justice kagan',
            'justice jackson', 'justice barrett', 'justice kavanaugh',
            'justice thomas', 'justice alito', 'justice gorsuch',
            'federal judge rules', 'federal court rules',
            'district court rules', 'circuit court rules',
            'dc circuit ruling', 'fifth circuit ruling', 'ninth circuit ruling',
            'court blocks executive order', 'court strikes down eo',
            'court issues injunction', 'court denies stay',
            'doj statement', 'attorney general statement',
            'department of justice', 'us attorney',
            'doj indicts', 'doj investigation', 'doj prosecution',
            'fbi director', 'fbi statement',
            'judge issues contempt', 'court orders compliance',
        ],
        'tripwires': [
            'scotus blocks executive order', 'court orders president',
            'court holds in contempt', 'court issues nationwide injunction',
            'doj resignation', 'mass doj resignation',
            'court orders troops withdrawn', 'judicial defiance',
            'scotus rules against', 'supreme court overturns',
        ],
        'baseline_statements_per_week': 25,
    },

    # ⭐ NEW: DHS / ICE — highest-volatility domestic vector
    'us_dhs_ice': {
        'name':  'DHS / ICE / Immigration Enforcement',
        'flag':  '🇺🇸',
        'icon':  '🚨',
        'color': '#c2410c',
        'role':  'Immigration Enforcement Rhetoric & Civil Unrest Driver',
        'layer': 'institutional',
        'weight': 1.1,
        'description': (
            'DHS Secretary, ICE Director, CBP, and immigration enforcement rhetoric. '
            'Currently the highest-volatility domestic signal vector and a leading '
            'indicator for protests + civil unrest + midterm voter mobilization. '
            'Election window (Nov 2026): enforcement near polling or counting sites is '
            'tracked in the governance block. Watch for: ICE raids announcements, '
            'mass deportation language, sanctuary city rhetoric, CBP enforcement actions, '
            'DHS funding clips.'
        ),
        'keywords': [
            'ice raid', 'ice raids', 'ice enforcement', 'ice operation',
            'ice arrests', 'ice detention', 'ice deportation',
            'mass deportation', 'mass roundup',
            'dhs announces', 'dhs secretary', 'secretary mullin', 'dhs statement',
            'cbp announces', 'border patrol', 'border enforcement',
            'sanctuary city', 'sanctuary jurisdiction',
            'immigration enforcement', 'immigration raid',
            'workplace raid', 'workplace enforcement',
            'tom homan', 'border czar homan', 'homan statement',
            'ice acting director', 'ice director',
            'family separation', 'detention center',
            'asylum seekers', 'border crossing',
            'immigration crackdown', 'immigrant communities',
            'protest ice', 'ice protest', 'anti-ice protest',
            'sanctuary protest', 'immigrant rights protest',
            'dhs funding', 'dhs shutdown', 'ice budget',
            # Spanish
            'ice redada', 'redadas migratorias', 'deportación masiva',
            'agentes de migración', 'migra',
        ],
        'tripwires': [
            'mass ice raids', 'ice raids reported',
            'ice deploys troops', 'national guard ice',
            'ice kills', 'ice shoots', 'ice fatal',
            'ice raid sparks protests', 'ice riots',
            'mass deportation begins', 'deportation flights',
            'sanctuary city defies', 'governor blocks ice',
            'troops deployed enforce immigration',
        ],
        'baseline_statements_per_week': 40,
    },

    'us_federal_reserve': {
        'name':  'Federal Reserve',
        'flag':  '🇺🇸',
        'icon':  '💵',
        'color': '#059669',
        'role':  'Fed Chair + FOMC -- Markets-Stability Rhetoric',
        'layer': 'institutional',
        'weight': 0.85,
        'description': (
            'Fed Chair (Kevin Warsh since May 2026), FOMC statements, and Federal Reserve regional bank '
            'commentary. Distinct economic-stability signal because Fed independence '
            'rhetoric (vs executive pressure to cut rates) is a key institutional '
            'integrity indicator. Watch for: FOMC press conferences, dissent in FOMC '
            'votes, Fed chair-White House rhetoric, regional Fed statements.'
        ),
        'keywords': [
            'fed chair', 'fed chairman', 'kevin warsh', 'warsh said', 'chair warsh',
            'fomc statement', 'fomc decision', 'fomc minutes',
            'federal reserve announces', 'fed rate decision',
            'fed press conference', 'fed governors',
            'st louis fed', 'new york fed', 'kansas city fed',
            'fed independence', 'fed pressure',
            'trump fed', 'trump warsh', 'wh pressures fed',
            'fed dissent vote',
            'fed minutes show', 'fomc minutes',
            'rate cut', 'rate hike', 'rate hold',
            'beige book', 'fed beige book',
        ],
        'tripwires': [
            'fed chair resigns', 'fed chair fired', 'fed chair ousted',
            'fed independence threatened', 'fomc mass dissent',
            'fed governor resigns', 'emergency fomc meeting',
            'fed cuts emergency rate',
        ],
        'baseline_statements_per_week': 8,
    },

    'us_states': {
        'name':  'State Governors',
        'flag':  '🇺🇸',
        'icon':  '🗺️',
        'color': '#7c3aed',
        'role':  'State Pushback / Federalism Rhetoric',
        'layer': 'institutional',
        'weight': 0.85,
        'description': (
            'Major state governors (CA, TX, FL, NY, IL, WA, etc.) when they push back '
            'on federal posture or align with federal policy. Federalism-tension '
            'indicator. Watch for: governor lawsuits against federal actions, sanctuary '
            'state declarations, state national guard deployment disputes, governor-vs-'
            'WH rhetoric.'
        ),
        'keywords': [
            'governor newsom', 'governor abbott', 'governor desantis',
            # v1.4.0: departed governors removed; generic state-office forms added
            # so turnover (more in Jan 2027) does not silently blind this actor.
            'governor hochul', 'governor pritzker', 'governor whitmer',
            'governor shapiro', 'governor lee tennessee', 'governor walz',
            'virginia governor', 'new jersey governor', 'washington governor',
            'governor said', 'governor says', 'governor signs', 'governor orders',
            'state attorney general', 'state ag sues',
            'state files lawsuit', 'state sues federal',
            'state national guard', 'governor federalize',
            'sanctuary state', 'sanctuary declaration',
            'state vs federal', 'governor pushes back',
            'red state blue state', 'governor defies',
            'state of the state',
            'governors association', 'national governors',
        ],
        'tripwires': [
            'governor refuses federal', 'governor defies federal',
            'state national guard refuses',
            'state secedes', 'state nullifies',
            'governor invokes states rights',
            'state files supreme court',
        ],
        'baseline_statements_per_week': 20,
    },

    # ⭐ NEW v1.4.0 (Nov 1 2026, Rachel's ruling): TWO-SIDED civil-society
    # mobilization. Outside organisations that drive turnout, rallies and
    # pressure campaigns, counted PER SIDE so the reading is symmetric by
    # construction. Feeds the composite like any actor; the per-side split
    # is reported in 'mobilization'. Before Election Day this is campaign
    # context; after it, results-driven mobilization is the signal.
    'us_civil_mobilization': {
        'name':  'Civil-Society Mobilization (two-sided)',
        'flag':  '🇺🇸',
        'icon':  '📣',
        'color': '#0f766e',
        'role':  'Left- and right-leaning movements and advocacy groups -- turnout, rallies, pressure',
        'layer': 'institutional',
        'weight': 0.8,
        'description': (
            'Influential outside organisations on both sides, counted separately. '
            'Left-leaning: No Kings, Indivisible, MoveOn, Lincoln Project. '
            'Right-leaning: Turning Point Action/USA, MAGA Inc., Heritage Action, '
            'Americans for Prosperity. Campaign-season volume is normal democracy; '
            'after Election Day, mobilization about the RESULTS is what matters.'
        ),
        'keywords_left': [
            'no kings', 'indivisible group', 'indivisible organizers', 'indivisible activists',
            'indivisible chapters', 'indivisible protest', 'ezra levin', 'leah greenberg',
            'moveon', 'lincoln project',
        ],
        'keywords_right': [
            'turning point action', 'turning point usa', 'tpusa', 'maga inc',
            'heritage action', 'americans for prosperity',
        ],
        'keywords_unsided': [
            'nationwide protests', 'nationwide protest', 'mass rally', 'march on washington',
            'protesters gathered', 'rally outside the capitol',
        ],
        'keywords': [],   # filled below from the three lists
        'tripwires': [
            'protesters storm', 'clashes at rally', 'rally turns violent',
            'protest at election office', 'protest at counting center',
        ],
        'baseline_statements_per_week': 15,
    },
}
ACTORS['us_civil_mobilization']['keywords'] = (
    ACTORS['us_civil_mobilization']['keywords_left'] +
    ACTORS['us_civil_mobilization']['keywords_right'] +
    ACTORS['us_civil_mobilization']['keywords_unsided'])


# Layer ordering for frontend display
LAYER_ORDER = ['executive', 'legislative', 'institutional']

# Convenience: list of actor keys in display order (executive first, then legislative, then institutional)
ACTOR_DISPLAY_ORDER = [
    'us_executive', 'us_state_dept', 'us_defense',
    'us_congress_majority', 'us_congress_opposition',
    'us_judicial', 'us_dhs_ice', 'us_federal_reserve', 'us_states',
    'us_civil_mobilization',
]


# ════════════════════════════════════════════════════════════════════
# RSS FEEDS — per-actor + general US politics
# ════════════════════════════════════════════════════════════════════
# Browser UA already used in _fetch_rss to bypass bot blocks
# ════════════════════════════════════════════════════════════════════

US_RHETORIC_RSS = [
    # ── General politics / news ──
    ('NYT Politics',     'https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml',   'eng', 1.0),
    ('NYT US',           'https://rss.nytimes.com/services/xml/rss/nyt/US.xml',         'eng', 1.0),
    ('NPR National',     'https://feeds.npr.org/1003/rss.xml',                          'eng', 1.0),
    ('The Hill',         'https://thehill.com/news/feed/',                              'eng', 0.95),
    ('Politico (via Google News)', 'https://news.google.com/rss/search?q=site%3Apolitico.com&hl=en-US&gl=US&ceid=US:en', 'eng', 0.9),
    ('Axios',            'https://api.axios.com/feed/',                                  'eng', 0.95),
    ('CNN Politics',     'http://rss.cnn.com/rss/cnn_allpolitics.rss',                  'eng', 0.9),
    ('PBS NewsHour',     'https://www.pbs.org/newshour/feeds/rss/headlines',            'eng', 0.95),
    ('ProPublica',       'https://www.propublica.org/feeds/propublica/main',            'eng', 0.95),
    ('WaPo Politics',    'https://feeds.washingtonpost.com/rss/politics',               'eng', 1.0),
    ('Atlantic Politics','https://www.theatlantic.com/feed/channel/politics/',          'eng', 0.9),
    ('AP US (via Google News)', 'https://news.google.com/rss/search?q=site%3Aapnews.com+politics&hl=en-US&gl=US&ceid=US:en', 'eng', 1.0),

    # ── Cross-spectrum balance ──
    ('Washington Examiner', 'https://www.washingtonexaminer.com/news/feed',             'eng', 0.85),
    ('National Review',  'https://www.nationalreview.com/feed/',                        'eng', 0.85),
    ('Reason',           'https://reason.com/feed/',                                    'eng', 0.8),

    # ── Legal / institutional ──
    ('Just Security (via Google News)', 'https://news.google.com/rss/search?q=site%3Ajustsecurity.org&hl=en-US&gl=US&ceid=US:en', 'eng', 0.95),
    ('Lawfare (via Google News)', 'https://news.google.com/rss/search?q=site%3Alawfaremedia.org&hl=en-US&gl=US&ceid=US:en', 'eng', 0.95),
    ('SCOTUSblog',       'https://www.scotusblog.com/feed/',                             'eng', 1.0),

    # ── DHS / immigration enforcement specialist ──
    ('DHS/ICE (via Google News)', 'https://news.google.com/rss/search?q=ICE+raid+OR+deportation+OR+%22immigration+enforcement%22&hl=en-US&gl=US&ceid=US:en', 'eng', 1.05),

    # ── Cyber / infrastructure (cross-cutting) ──
    ('CISA Alerts',      'https://www.cisa.gov/news.xml',                                'eng', 0.95),

    # ── Allied foreign view (US-focused) ──
    ('BBC US & Canada',  'https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml',   'eng', 0.95),
    ('Guardian US',      'https://www.theguardian.com/us-news/rss',                     'eng', 0.95),

    # ── v1.4.0: election administration (counting / certification window) ──
    ('Election certification (via Google News)', 'https://news.google.com/rss/search?q=%22certify%22+OR+%22certification%22+OR+recount+election+when:3d&hl=en-US&gl=US&ceid=US:en', 'eng', 1.0),
    ('Election officials (via Google News)', 'https://news.google.com/rss/search?q=%22election+officials%22+OR+%22poll+workers%22+OR+%22polling+place%22+when:3d&hl=en-US&gl=US&ceid=US:en', 'eng', 0.95),
    ('Civil mobilization (via Google News)', 'https://news.google.com/rss/search?q=%22No+Kings%22+OR+Indivisible+OR+%22Turning+Point+Action%22+OR+%22Heritage+Action%22+OR+MoveOn+OR+%22Americans+for+Prosperity%22+when:7d&hl=en-US&gl=US&ceid=US:en', 'eng', 0.9),

    # ── Spanish-language US-focused ──
    ('Spanish-language US Politics (via Google News)', 'https://news.google.com/rss/search?q=Estados+Unidos+pol%C3%ADtica+OR+Trump+OR+Casa+Blanca&hl=es-419&gl=US&ceid=US:es-419', 'spa', 0.85),
]


# ════════════════════════════════════════════════════════════════════
# GDELT QUERIES (per-actor + general)
# ════════════════════════════════════════════════════════════════════

GDELT_QUERIES = [
    # General executive rhetoric
    ('"trump statement" OR "trump announces" OR "white house statement"',     'eng', 1.0),
    ('"trump truth social" OR "truth social post"',                            'eng', 1.0),
    # Cabinet
    ('"secretary rubio" OR "state department" OR "rubio statement"',           'eng', 0.95),
    ('"secretary hegseth" OR "pentagon" OR "defense secretary"',               'eng', 0.95),
    ('"secretary mullin" OR "dhs secretary" OR "homeland security"',           'eng', 1.0),
    # Legislative
    ('"speaker johnson" OR "house republicans" OR "senate gop"',               'eng', 0.9),
    ('"hakeem jeffries" OR "senate democrats" OR "house democrats"',           'eng', 0.9),
    # Judicial
    ('"supreme court" ruling OR decision OR strikes',                          'eng', 0.95),
    ('"federal judge" rules OR injunction OR blocks',                          'eng', 0.9),
    # ICE / immigration
    ('"ice raids" OR "ice arrests" OR "mass deportation"',                     'eng', 1.05),
    ('"sanctuary city" OR "sanctuary state" OR "immigration enforcement"',     'eng', 1.0),
    # Federal Reserve
    ('"fed chair" OR "federal reserve" OR "fomc"',                             'eng', 0.85),
    # v1.4.0: election administration + two-sided mobilization
    ('"certify" OR "recount" OR "election officials" OR "concede"',            'eng', 1.0),
    # State pushback
    ('"governor" sues OR defies OR "state attorney general"',                  'eng', 0.85),
    # Spanish
    ('"trump declara" OR "casa blanca"',                                       'spa', 0.85),
    ('"redadas migratorias" OR "deportación masiva"',                          'spa', 0.95),
]


# ════════════════════════════════════════════════════════════════════
# TIER THRESHOLDS (calibration per Rachel May 2026)
# ════════════════════════════════════════════════════════════════════
# Score is volatility/coherence-based (per D4):
#   STABLE    0-25   coherent posture, low partisan divergence
#   ACTIVE    26-50  assertive posture, normal disagreement (current state)
#   VOLATILE  51-75  sharp divergence, branches contradicting
#   CRISIS    76-100 branches openly fighting, allies breaking publicly

TIER_THRESHOLDS = [
    (0,  'L0', 'Stable',     'STABLE',   '🟢', 'Coherent posture, low partisan divergence, allies aligned'),
    (26, 'L1', 'Active',     'ACTIVE',   '🟢', 'Assertive posture, normal disagreement, manageable'),
    (38, 'L2', 'Active+',    'ACTIVE',   '🟡', 'Assertive posture trending volatile'),
    (51, 'L3', 'Volatile',   'VOLATILE', '🟠', 'Sharp partisan divergence, allies distancing'),
    (66, 'L4', 'Volatile+',  'VOLATILE', '🔴', 'Branches contradicting, allies publicly skeptical'),
    (76, 'L5', 'Crisis',     'CRISIS',   '🔴', 'Branches openly fighting, multiple foreign actors targeting US'),
]


def _get_tier(score):
    """Return (tier_level, tier_name, tier_band, icon, description) for a score."""
    selected = TIER_THRESHOLDS[0]
    for entry in TIER_THRESHOLDS:
        if score >= entry[0]:
            selected = entry
    return selected[1], selected[2], selected[3], selected[4], selected[5]


# ════════════════════════════════════════════════════════════════════
# REDIS HELPERS (Upstash REST)
# ════════════════════════════════════════════════════════════════════

def _redis_get(key):
    """Fetch a key from Upstash Redis. Returns parsed JSON or None.

    Now LOUD on infrastructure failure (May 2026): we don't log
    every key-not-found (too noisy) but DO log auth/network errors.
    """
    if not REDIS_AVAILABLE:
        return None
    try:
        url = f"{UPSTASH_URL}/get/{urllib.parse.quote(key, safe='')}"
        resp = requests.get(url, headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'}, timeout=8)
        if resp.status_code != 200:
            print(f"[US Rhetoric] ⚠️ Redis GET HTTP {resp.status_code} for {key}: {resp.text[:200]}")
            return None
        result = resp.json().get('result')
        if result is None:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result
    except Exception as e:
        print(f"[US Rhetoric] ❌ Redis GET exception for {key}: {type(e).__name__}: {str(e)[:200]}")
        return None


MILITARY_CAPABILITY_KEY = 'military:us:capability_direction'


def read_military_capability(actor='us'):
    """Read the military tracker's signed capability fingerprint.

    This is the WHA half of the capability-rhetoric join. The military
    tracker publishes military:{actor}:capability_direction every scan;
    this pulls it so rhetoric can be set against measured capability.

    Returns the fingerprint dict, or None. Never raises: if the military
    read is missing the interpreter says so explicitly rather than
    silently reporting no divergence.
    """
    try:
        fp = _redis_get(f'military:{actor}:capability_direction')
        if isinstance(fp, dict) and fp:
            print(f"[US Rhetoric] Military capability read: {actor} "
                  f"net {fp.get('net_score')} "
                  f"(proj {fp.get('projection_score')} / loss {fp.get('loss_score')}, "
                  f"classified {fp.get('classified_share')}, "
                  f"scanned {fp.get('scanned_at')})")
            return fp
        print(f"[US Rhetoric] Military capability fingerprint absent for {actor} "
              f"-- capability-rhetoric join will report a coverage gap")
    except Exception as e:
        print(f"[US Rhetoric] Military capability read failed: {str(e)[:120]}")
    return None


def _redis_set(key, value, ttl=None):
    """Set a key in Upstash Redis. Returns True on success.

    Now LOUD on failure (May 2026): logs every failure type so we can
    distinguish env var issues, network issues, auth issues, etc.
    """
    if not REDIS_AVAILABLE:
        print(f"[US Rhetoric] ❌ Redis SET SKIPPED for {key} -- REDIS_AVAILABLE is False (URL len={len(UPSTASH_URL)}, TOKEN len={len(UPSTASH_TOKEN)})")
        return False
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        url = f"{UPSTASH_URL}/set/{urllib.parse.quote(key, safe='')}"
        params = {'EX': ttl} if ttl else {}
        resp = requests.post(
            url,
            data=value,
            headers={'Authorization': f'Bearer {UPSTASH_TOKEN}', 'Content-Type': 'text/plain'},
            params=params,
            timeout=8,
        )
        if resp.status_code == 200:
            print(f"[US Rhetoric] ✅ Redis SET ok for {key} ({len(str(value))} bytes)")
            return True
        else:
            print(f"[US Rhetoric] ❌ Redis SET failed for {key} -- HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[US Rhetoric] ❌ Redis SET exception for {key}: {type(e).__name__}: {str(e)[:200]}")
        return False


def _redis_lpush_trim(key, value, max_len=336):
    """Push a value onto a Redis list and trim to max_len. (12 weeks * 28 = 336 by default)"""
    if not REDIS_AVAILABLE:
        return False
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        url_push = f"{UPSTASH_URL}/lpush/{urllib.parse.quote(key, safe='')}/{urllib.parse.quote(value, safe='')}"
        resp = requests.post(url_push, headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'}, timeout=8)
        if resp.status_code != 200:
            return False
        url_trim = f"{UPSTASH_URL}/ltrim/{urllib.parse.quote(key, safe='')}/0/{max_len-1}"
        requests.post(url_trim, headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'}, timeout=8)
        return True
    except Exception as e:
        print(f"[US Rhetoric] Redis LPUSH error for {key}: {str(e)[:120]}")
        return False


# ════════════════════════════════════════════════════════════════════
# ARTICLE FETCHING (RSS / GDELT / NewsAPI / Brave / Social)
# ════════════════════════════════════════════════════════════════════

def _parse_pub_date(pub_str):
    """Parse a publish date from various formats. Returns datetime or None."""
    if not pub_str:
        return None
    formats = [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
    except Exception:
        return None


# =====================================================================
# SOURCE HEALTH INSTRUMENTATION (v1.3, Sep 19 2026)
# =====================================================================
# The *_AVAILABLE flags above are CONFIGURATION checks, not health checks.
# BRAVE_AVAILABLE is literally bool(BRAVE_API_KEY): it reports that a key
# string exists, and has never had anything to do with whether Brave answers.
# On Sep 19 the payload showed brave/newsapi/reddit/telegram all "available"
# while three of them contributed zero articles, because every fetcher below
# discards its status code and returns [].
#
# That made one standing question unanswerable from outside: is a dead feed a
# 403, a burnt quota, a soft block, or a query that matches nothing? Those
# have four different fixes and looked identical.
#
# This block records the outcome of every fetch attempt. It changes nothing
# about what is fetched or how anything is scored - it is strictly a
# measurement, deliberately shipped ahead of any attempt to revive a feed so
# the corpus stays comparable across the change.
# Sources this tracker is supposed to have. A name here that never appears
# in _SOURCE_HEALTH is reported as 'not_attempted' rather than vanishing
# from the payload, which is how brave and telegram went missing from
# source_counts without anyone noticing.
EXPECTED_SOURCES = ('rss', 'gdelt', 'newsapi', 'brave',
                    'bluesky', 'telegram', 'reddit')

_SOURCE_HEALTH = {}


def _health_reset():
    """Clear per-scan health records. Called once at the top of a scan."""
    global _SOURCE_HEALTH
    _SOURCE_HEALTH = {}


def _health_note(source, configured=True, http_status=None, error=None,
                 articles=0, duration_ms=None, note=None):
    """Record one fetch attempt. Many attempts aggregate into one source."""
    rec = _SOURCE_HEALTH.setdefault(source, {
        'configured':    configured,
        'attempts':      0,
        'articles':      0,
        'http_statuses': {},
        'errors':        [],
        'notes':         [],
        'duration_ms':   0,
    })
    rec['configured'] = configured
    rec['attempts'] += 1
    rec['articles'] += int(articles or 0)
    if http_status is not None:
        key = str(http_status)
        rec['http_statuses'][key] = rec['http_statuses'].get(key, 0) + 1
    if error and len(rec['errors']) < 3:
        rec['errors'].append(str(error)[:160])
    if note and note not in rec['notes']:
        rec['notes'].append(str(note)[:120])
    if duration_ms:
        rec['duration_ms'] += int(duration_ms)


def _health_status(rec):
    """One word for what happened to this source. The whole point is that
    'we could not reach it' and 'we reached it and asked the wrong question'
    stop looking the same."""
    if not rec.get('configured'):
        return 'not_configured'
    if rec.get('attempts', 0) == 0:
        # Never called at all. Brave in particular sits behind a
        # news_index_total < 60 gate, so a healthy GDELT silently disables it.
        return 'not_attempted'
    statuses = rec.get('http_statuses') or {}
    if any(s in statuses for s in ('401', '403')):
        return 'auth_failed'
    if '429' in statuses:
        return 'rate_limited'
    non_ok = [s for s in statuses if s not in ('200', 'None')]
    if non_ok:
        # v1.5.1: RSS is many feeds. If some answered with articles, the
        # source DELIVERED -- 'http error' on the page next to "1,092 articles"
        # read as a contradiction. Partial is the true word.
        return 'partial' if rec.get('articles', 0) > 0 else 'http_error'
    if rec.get('errors'):
        return 'error'
    if rec.get('articles', 0) > 0:
        return 'ok'
    return 'reachable_but_empty'


def _health_report(expected=()):
    """Per-source health for the scan payload.

    `expected` names sources that are supposed to run, so one that was never
    attempted is reported as absent rather than silently missing from the dict
    - which is exactly how brave and telegram disappeared from source_counts.
    """
    out = {}
    for name in set(list(_SOURCE_HEALTH.keys()) + list(expected)):
        rec = _SOURCE_HEALTH.get(name) or {
            'configured': True, 'attempts': 0, 'articles': 0,
            'http_statuses': {}, 'errors': [], 'notes': [], 'duration_ms': 0,
        }
        out[name] = {
            'status':        _health_status(rec),
            'configured':    rec['configured'],
            'attempts':      rec['attempts'],
            'articles':      rec['articles'],
            'http_statuses': rec['http_statuses'],
            'duration_ms':   rec['duration_ms'],
            'error':         (rec['errors'][0] if rec['errors'] else None),
            'notes':         rec['notes'],
        }
    return out


def _fetch_rss(url, source_name, weight=0.85, lang='eng', max_items=20):
    """Fetch RSS feed and return list of article dicts."""
    _t0 = time.time()
    try:
        resp = requests.get(url, timeout=RSS_TIMEOUT_SEC, headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'X-Asifah-Source': 'asifahanalytics.com OSINT stability monitor',
        })
        if resp.status_code != 200:
            print(f"[US Rhetoric RSS] {source_name}: HTTP {resp.status_code}")
            _health_note('rss', http_status=resp.status_code,
                         duration_ms=(time.time() - _t0) * 1000,
                         note=f'{source_name}: HTTP {resp.status_code}')
            return []

        root = ET.fromstring(resp.content)
        items = []
        for item in (root.iter('item') or []):
            title = (item.find('title').text if item.find('title') is not None else '') or ''
            link  = (item.find('link').text  if item.find('link')  is not None else '') or ''
            desc  = (item.find('description').text if item.find('description') is not None else '') or ''
            pub   = (item.find('pubDate').text if item.find('pubDate') is not None else '') or ''
            items.append({
                'title':       title.strip(),
                'description': desc.strip(),
                'link':        link.strip(),
                'published':   pub.strip(),
                'source':      f'rss/{source_name}',
                'source_type': 'rss',
                'language':    lang,
                'weight':      weight,
            })
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        print(f"[US Rhetoric RSS] {source_name}: error {str(e)[:120]}")
        return []


# Shared GDELT gateway (Jul 23 2026) -- one paced, serialised path to GDELT for
# every tracker on this backend. A live scan showed seven WHA trackers calling
# api.gdeltproject.org concurrently from one process; GDELT throttled and every
# caller timed out, contributing ZERO articles backend-wide.
try:
    from gdelt_gateway import gdelt_fetch as _gw_fetch
    _GDELT_GATEWAY = True
except ImportError:
    print("[US Rhetoric] gdelt_gateway not available -- using direct GDELT calls")
    _GDELT_GATEWAY = False

def _fetch_gdelt(query, language='eng', days=3, max_records=25, weight=0.95):
    """Fetch from GDELT 2.0 DOC API -- routed through the shared gateway.

    This tracker's article shape is the most divergent on the backend: it uses
    `link` rather than `url`, `source_type` rather than `feed_type`, and
    prefixes the source with 'gdelt/'. All preserved verbatim -- the gateway
    adapts to the caller, never the other way round.
    """
    if _GDELT_GATEWAY:
        _t0 = time.time()
        raw = _gw_fetch(query, language=language, timespan=f'{days*24}h',
                        maxrecords=max_records, label=f'us/{language}')
        # The gateway swallows its own transport detail, so the only thing
        # observable from here is whether it returned anything. Recorded
        # explicitly so a dead gateway is not mistaken for a dead GDELT.
        _health_note('gdelt', articles=len(raw or []),
                     duration_ms=(time.time() - _t0) * 1000,
                     http_status=200 if raw else None,
                     note='routed through shared GDELT gateway')
        return [{
            'title':       a.get('title', ''),
            'description': '',
            'link':        a.get('url', ''),
            'published':   a.get('published', ''),
            'source':      f"gdelt/{a.get('source') or 'unknown'}",
            'source_type': 'gdelt',
            'language':    language,
            'weight':      weight,
        } for a in (raw or [])]

    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': str(max_records),
            'format':     'json',
            'sort':       'datedesc',
            'sourcelang': language,
            'timespan':   f'{days*24}h',
        }
        url = 'https://api.gdeltproject.org/api/v2/doc/doc?' + urllib.parse.urlencode(params)
        resp = requests.get(url, timeout=GDELT_TIMEOUT_SEC)
        if resp.status_code == 429:
            print(f"[US Rhetoric GDELT] 429 rate limit -- skipping: {language}")
            _health_note('gdelt', http_status=429, note='rate limited')
            return []
        if resp.status_code != 200:
            print(f"[US Rhetoric GDELT] HTTP {resp.status_code}")
            _health_note('gdelt', http_status=resp.status_code)
            return []
        try:
            data = resp.json()
        except Exception:
            print(f"[US Rhetoric GDELT] {language}: non-JSON response (soft block)")
            # 200 OK carrying HTML is GDELT's soft block. It is neither an
            # outage nor a query problem and needs its own label.
            _health_note('gdelt', http_status=200,
                         note='HTTP 200 with non-JSON body (soft block)')
            return []

        articles = []
        for art in (data.get('articles') or []):
            articles.append({
                'title':       art.get('title', ''),
                'description': '',
                'link':        art.get('url', ''),
                'published':   art.get('seendate', ''),
                'source':      f'gdelt/{art.get("domain","unknown")}',
                'source_type': 'gdelt',
                'language':    language,
                'weight':      weight,
            })
        return articles
    except requests.exceptions.Timeout:
        print(f"[US Rhetoric GDELT] timeout (>8s) -- breaking circuit")
        return []
    except Exception as e:
        print(f"[US Rhetoric GDELT] error: {str(e)[:120]}")
        return []


def _fetch_newsapi(query, max_records=15, weight=0.9, have=None):
    """Fetch from NewsAPI as fallback when GDELT struggles.

    v1.4.0: through newsapi_gateway when present. The gateway decides whether
    to spend budget (GDELT blind, or this caller thin) and says why when it
    does not -- recorded as a note, so a deliberate skip is not 'empty'."""
    if _newsapi_gw is not None:
        _t0 = time.time()
        try:
            raw, probe = _newsapi_gw(query, days=3, page_size=max_records,
                                     label='us/' + query.split()[0].strip('"').lower(),
                                     have=have)
        except Exception as e:
            _health_note('newsapi', error=e, duration_ms=(time.time() - _t0) * 1000)
            return []
        arts = [{
            'title':       a.get('title', '') or '',
            'description': a.get('description', '') or '',
            'link':        a.get('url', '') or '',
            'published':   a.get('publishedAt', '') or '',
            'source':      f"newsapi/{(a.get('source') or {}).get('name', 'unknown')}",
            'source_type': 'newsapi',
            'language':    'eng',
            'weight':      weight,
        } for a in (raw or [])]
        _health_note('newsapi', http_status=probe.get('http_status') or (200 if probe.get('sensed') else None),
                     articles=len(arts), duration_ms=(time.time() - _t0) * 1000,
                     note=f"gateway: {probe.get('reason')}")
        return arts
    if not NEWSAPI_AVAILABLE:
        _health_note('newsapi', configured=False)
        return []
    _t0 = time.time()
    try:
        url = 'https://newsapi.org/v2/everything'
        params = {
            'q':        query,
            'pageSize': max_records,
            'sortBy':   'publishedAt',
            'language': 'en',
            'apiKey':   NEWSAPI_KEY,
        }
        resp = requests.get(url, params=params, timeout=NEWSAPI_TIMEOUT_SEC)
        if resp.status_code == 429:
            print(f"[US Rhetoric NewsAPI] 429 rate limit -- skipping")
            _health_note('newsapi', http_status=429, note='rate limited')
            return []
        if resp.status_code != 200:
            # Previously a bare return []. NewsAPI answers a plan
            # restriction with 426 and a bad key with 401; both looked
            # exactly like 'no results' from outside this function.
            _health_note('newsapi', http_status=resp.status_code,
                         error=(resp.text or '')[:160],
                         duration_ms=(time.time() - _t0) * 1000)
            return []
        data = resp.json()
        articles = []
        for art in (data.get('articles') or []):
            articles.append({
                'title':       art.get('title', '') or '',
                'description': art.get('description', '') or '',
                'link':        art.get('url', '') or '',
                'published':   art.get('publishedAt', '') or '',
                'source':      f"newsapi/{(art.get('source') or {}).get('name', 'unknown')}",
                'source_type': 'newsapi',
                'language':    'eng',
                'weight':      weight,
            })
        _health_note('newsapi', http_status=200, articles=len(articles),
                     duration_ms=(time.time() - _t0) * 1000)
        return articles
    except Exception as e:
        print(f"[US Rhetoric NewsAPI] error: {str(e)[:120]}")
        _health_note('newsapi', error=e,
                     duration_ms=(time.time() - _t0) * 1000)
        return []


def _fetch_brave(query, max_records=15, weight=0.85):
    """Brave Search fallback (free tier, 2000 queries/month)."""
    if not BRAVE_AVAILABLE:
        _health_note('brave', configured=False)
        return []
    _t0 = time.time()
    try:
        url = 'https://api.search.brave.com/res/v1/news/search'
        params = {'q': query, 'count': max_records}
        resp = requests.get(url, params=params, timeout=8, headers={
            'Accept': 'application/json',
            'X-Subscription-Token': BRAVE_API_KEY,
        })
        if resp.status_code != 200:
            # The line this replaces is why 'is it a 403, a keyword error,
            # or did we burn the quota' could not be answered. Brave sends
            # 401 for a bad token, 403 for a plan problem and 429 when the
            # 2000/month free tier is spent; all three returned [].
            _health_note('brave', http_status=resp.status_code,
                         error=(resp.text or '')[:160],
                         duration_ms=(time.time() - _t0) * 1000)
            return []
        data = resp.json()
        articles = []
        for art in (data.get('results') or []):
            articles.append({
                'title':       art.get('title', '') or '',
                'description': art.get('description', '') or '',
                'link':        art.get('url', '') or '',
                'published':   art.get('age', '') or '',
                'source':      f"brave/{art.get('meta_url',{}).get('hostname','unknown')}",
                'source_type': 'brave',
                'language':    'eng',
                'weight':      weight,
            })
        _health_note('brave', http_status=200, articles=len(articles),
                     duration_ms=(time.time() - _t0) * 1000)
        return articles
    except Exception as e:
        print(f"[US Rhetoric Brave] error: {str(e)[:120]}")
        _health_note('brave', error=e,
                     duration_ms=(time.time() - _t0) * 1000)
        return []


def _fetch_all_articles():
    """Aggregate articles from all sources (RSS + GDELT + NewsAPI + Brave + social)."""
    _health_reset()
    all_articles = []

    # ── RSS ──
    rss_count = 0
    for url, name, lang, weight in [(t[1], t[0], t[2], t[3]) for t in US_RHETORIC_RSS]:
        rss = _fetch_rss(url, name, weight=weight, lang=lang)
        all_articles.extend(rss)
        rss_count += len(rss)
        time.sleep(0.3)  # gentle pacing
    _health_note('rss', articles=rss_count, http_status=200)
    print(f"[US Rhetoric] RSS: {rss_count} articles")

    # ── GDELT ──
    gdelt_count = 0
    gdelt_failed = 0
    for query, lang, weight in GDELT_QUERIES:
        if gdelt_failed >= 3:
            print(f"[US Rhetoric GDELT] Circuit broken after 3 failures -- skipping rest")
            break
        articles = _fetch_gdelt(query, language=lang, days=3, weight=weight)
        if not articles:
            gdelt_failed += 1
        else:
            gdelt_failed = 0
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)
    print(f"[US Rhetoric] GDELT: {gdelt_count} articles")

    # ── NewsAPI fallback (if GDELT thin) ──
    newsapi_count = 0
    if not (gdelt_count < 30 and NEWSAPI_AVAILABLE):
        # NewsAPI is a conditional fallback. Never firing is a different
        # state from firing and failing, and the payload has never said
        # which one happened.
        _health_note('newsapi', configured=NEWSAPI_AVAILABLE,
                     note=f'not attempted: gdelt_count={gdelt_count} '
                          f'(fallback fires below 30)')
        _SOURCE_HEALTH['newsapi']['attempts'] = 0
    if gdelt_count < 30 and NEWSAPI_AVAILABLE:
        print(f"[US Rhetoric] GDELT thin ({gdelt_count}) -- triggering NewsAPI fallback")
        pre_newsapi = len(all_articles)
        for q in [
            '"trump statement" OR "white house"',
            '"certify" OR "recount" OR "election officials"',
            '"supreme court ruling" united states',
        ]:
            articles = _fetch_newsapi(q, max_records=10, have=gdelt_count)
            all_articles.extend(articles)
        newsapi_count = len(all_articles) - pre_newsapi
        print(f"[US Rhetoric] NewsAPI fallback: {newsapi_count} articles")

    # ── Brave fallback (NEW LOGIC May 2026): fires when GDELT + NewsAPI combined
    # is thin, independent of RSS/social health. Different source types serve
    # different analytical purposes — keyword-driven news-index discovery should
    # be backstopped even if curated RSS + social are healthy. Brave free tier
    # is 2000/month so we can spend the requests freely.
    news_index_total = gdelt_count + newsapi_count
    if not (news_index_total < 60 and BRAVE_AVAILABLE):
        _health_note('brave', configured=BRAVE_AVAILABLE,
                     note=f'not attempted: news_index_total='
                          f'{news_index_total} (fallback fires below 60)')
        _SOURCE_HEALTH['brave']['attempts'] = 0
    if news_index_total < 60 and BRAVE_AVAILABLE:
        print(f"[US Rhetoric] News-index thin (GDELT={gdelt_count} + NewsAPI={newsapi_count} = {news_index_total}) -- triggering Brave fallback")
        pre_brave = len(all_articles)
        for q in [
            'trump white house statement',
            'ice raids deportation',
            'supreme court ruling united states',
            'congress democrats republicans',
            'federal reserve chair',
            'election certification recount',
            'state governor lawsuit federal',
        ]:
            articles = _fetch_brave(q, max_records=10)
            all_articles.extend(articles)
        brave_count = len(all_articles) - pre_brave
        print(f"[US Rhetoric] Brave fallback: {brave_count} articles")

    # ── Bluesky ──
    if not BLUESKY_AVAILABLE:
        _health_note('bluesky', configured=False)
    if BLUESKY_AVAILABLE:
        _bs_t0 = time.time()
        try:
            bluesky_raw = fetch_bluesky_for_target('us', days=7, max_posts_per_account=20)
            transformed = []
            for p in bluesky_raw:
                # Defensive: source may be a dict — coerce to string
                raw_src = p.get('source')
                if isinstance(raw_src, dict):
                    src_str = raw_src.get('name', '') or f"Bluesky/{p.get('handle','unknown')}"
                else:
                    src_str = raw_src or f"Bluesky/{p.get('handle','unknown')}"
                transformed.append({
                    'title':       p.get('title') or p.get('text') or '',
                    'description': p.get('text') or p.get('description') or '',
                    'link':        p.get('url') or p.get('link') or '',
                    'published':   p.get('publishedAt') or p.get('published') or '',
                    'source':      str(src_str),
                    'source_type': 'bluesky',
                    'language':    'eng',
                    'weight':      1.0,
                })
            all_articles.extend(transformed)
            _health_note('bluesky', articles=len(transformed),
                         duration_ms=(time.time() - _bs_t0) * 1000)
            print(f"[US Rhetoric] Bluesky: +{len(transformed)} posts")
        except Exception as e:
            print(f"[US Rhetoric] Bluesky error: {str(e)[:120]}")
            _health_note('bluesky', error=e,
                         duration_ms=(time.time() - _bs_t0) * 1000)

    # ── Telegram ──
    if not TELEGRAM_AVAILABLE:
        _health_note('telegram', configured=False,
                     note='module import failed at startup')
    if TELEGRAM_AVAILABLE:
        _tg_t0 = time.time()
        try:
            tg_raw = fetch_telegram_signals_us(hours_back=7 * 24)
            transformed = []
            for p in tg_raw:
                # Defensive: source may be a dict — coerce to string
                raw_src = p.get('source')
                if isinstance(raw_src, dict):
                    src_str = raw_src.get('name', '') or f"Telegram/{p.get('channel','unknown')}"
                else:
                    src_str = raw_src or f"Telegram/{p.get('channel','unknown')}"
                transformed.append({
                    'title':       p.get('title') or p.get('text') or '',
                    'description': p.get('text') or p.get('description') or '',
                    'link':        p.get('url') or p.get('link') or '',
                    'published':   p.get('publishedAt') or p.get('published') or p.get('date') or '',
                    'source':      str(src_str),
                    'source_type': 'telegram',
                    'language':    'eng',
                    'weight':      0.95,
                })
            all_articles.extend(transformed)
            _health_note('telegram', articles=len(transformed),
                         duration_ms=(time.time() - _tg_t0) * 1000)
            print(f"[US Rhetoric] Telegram: +{len(transformed)} posts")
        except Exception as e:
            print(f"[US Rhetoric] Telegram error: {str(e)[:120]}")
            _health_note('telegram', error=e,
                         duration_ms=(time.time() - _tg_t0) * 1000)

    # ── Reddit ──
    if not REDDIT_AVAILABLE:
        _health_note('reddit', configured=False,
                     note='module import failed at startup')
    if REDDIT_AVAILABLE:
        _rd_t0 = time.time()
        try:
            reddit_articles = fetch_reddit_signals_us(days=7, max_per_sub=25)
            for r in reddit_articles:
                r.setdefault('language', 'eng')
                r.setdefault('weight', 0.9)
            all_articles.extend(reddit_articles)
            # Sep 19: every reddit lean bucket read 0 while reddit_available
            # reported True. If this records articles=0 with no error, the
            # module ran and returned nothing - a subreddit or auth problem
            # inside reddit_signals_us, not a problem here.
            _health_note('reddit', articles=len(reddit_articles),
                         duration_ms=(time.time() - _rd_t0) * 1000)
            print(f"[US Rhetoric] Reddit: +{len(reddit_articles)} posts")
        except Exception as e:
            print(f"[US Rhetoric] Reddit error: {str(e)[:120]}")
            _health_note('reddit', error=e,
                         duration_ms=(time.time() - _rd_t0) * 1000)

    # One line per source, so a dead feed is visible in the boot log
    # without waiting for anyone to inspect a payload.
    for _name, _rec in sorted(_health_report(EXPECTED_SOURCES).items()):
        if _rec['status'] != 'ok':
            print(f"[US Rhetoric HEALTH] {_name}: {_rec['status']} "
                  f"(articles={_rec['articles']}, attempts={_rec['attempts']}, "
                  f"http={_rec['http_statuses'] or '-'})")

    return all_articles


# ════════════════════════════════════════════════════════════════════
# CLASSIFICATION + SCORING
# ════════════════════════════════════════════════════════════════════

def _score_article_for_actor(article, actor_key, actor_def):
    """Score how well an article matches a specific actor. Returns (score, tripwire_hit)."""
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text = title + ' ' + desc

    score = 0
    matched_keywords = 0
    for kw in actor_def['keywords']:
        if kw.lower() in text:
            matched_keywords += 1
            score += 1
    if matched_keywords == 0:
        return 0, False

    tripwire_hit = False
    for tw in actor_def.get('tripwires', []):
        if tw.lower() in text:
            score += 5
            tripwire_hit = True

    base_weight = article.get('weight', 1.0)
    return score * base_weight, tripwire_hit


def _classify_articles(articles):
    """Classify articles by actor. Returns dict {actor_key: {articles, statement_count, tripwires}}."""
    seen_links = set()
    deduped = []
    for art in articles:
        link = art.get('link', '')
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        deduped.append(art)
    print(f"[US Rhetoric] Dedup: {len(articles)} -> {len(deduped)} articles")

    actor_results = {k: {'articles': [], 'statement_count': 0, 'tripwires': 0,
                          'total_score': 0.0, 'sample_articles': []}
                     for k in ACTORS.keys()}

    for art in deduped:
        for actor_key, actor_def in ACTORS.items():
            score, tripwire = _score_article_for_actor(art, actor_key, actor_def)
            if score > 0:
                actor_results[actor_key]['articles'].append(art)
                actor_results[actor_key]['statement_count'] += 1
                actor_results[actor_key]['total_score'] += score
                if tripwire:
                    actor_results[actor_key]['tripwires'] += 1
                if len(actor_results[actor_key]['sample_articles']) < 12:
                    actor_results[actor_key]['sample_articles'].append({
                        'title':     art.get('title', '')[:200],
                        'link':      art.get('link', ''),
                        'source':    art.get('source', ''),
                        'published': art.get('published', ''),
                        'language':  art.get('language', 'eng'),
                    })

    for actor_key, result in actor_results.items():
        actor_def = ACTORS[actor_key]
        baseline_3d = actor_def['baseline_statements_per_week'] * (3/7)
        ratio = result['statement_count'] / max(1.0, baseline_3d)
        # Volatility score: ratio above baseline indicates elevated activity
        # Cap at 100, scale so 1x baseline = 25, 2x = 50, 3x+ = 75-100
        if ratio <= 1.0:
            actor_score = 15 + ratio * 10  # 15-25 for normal
        elif ratio <= 2.0:
            actor_score = 25 + (ratio - 1) * 25  # 25-50
        elif ratio <= 3.0:
            actor_score = 50 + (ratio - 2) * 25  # 50-75
        else:
            actor_score = min(100, 75 + (ratio - 3) * 12.5)
        actor_score += result['tripwires'] * 8
        result['actor_score'] = min(100, round(actor_score, 1))
        result['baseline_ratio'] = round(ratio, 2)
        tier_lvl, tier_name, tier_band, tier_icon, tier_desc = _get_tier(result['actor_score'])
        result['tier'] = tier_lvl
        result['tier_name'] = tier_name
        result['tier_band'] = tier_band
        result['tier_icon'] = tier_icon
        result['tier_description'] = tier_desc

    return actor_results


# ════════════════════════════════════════════════════════════════════
# AGGREGATE COMPOSITE SCORE
# ════════════════════════════════════════════════════════════════════

def _compute_composite_score(actor_results):
    """Weighted average of actor scores -> composite US rhetoric score (0-100)."""
    total_weight = 0.0
    weighted_sum = 0.0
    for actor_key, result in actor_results.items():
        weight = ACTORS[actor_key]['weight']
        weighted_sum += result['actor_score'] * weight
        total_weight += weight
    composite = weighted_sum / total_weight if total_weight > 0 else 0
    return round(composite, 1)


# ════════════════════════════════════════════════════════════════════
# CROSS-THEATER FINGERPRINT (READ all + WRITE us_*)
# ════════════════════════════════════════════════════════════════════

# Full list of trackers to read fingerprints from
CROSS_THEATER_SOURCES = [
    # Middle East
    'iran', 'israel', 'lebanon', 'yemen', 'iraq', 'syria', 'oman',
    # Asia
    'china', 'taiwan', 'japan',  # 'dprk', 'india_pakistan' coming-soon
    # Europe
    'russia', 'belarus', 'ukraine', 'greenland',
    # Western Hemisphere
    'cuba', 'venezuela', 'mexico', 'panama', 'haiti', 'colombia', 'brazil',
    'peru', 'chile',
]


def _read_crosstheater_fingerprints():
    """
    Read cross-theater fingerprints via butterfly proxy.
    
    Replaced May 16 2026 — previously tried 3 Redis key conventions directly,
    which only succeeded for theaters writing 'fingerprint:<theater>:current'.
    Now calls butterfly_proxy_wha which fetches from ME backend's centralized
    butterfly reader, handling all 4 fingerprint storage patterns
    (envelope / atomic / shared-dict / snapshot).
    
    Returns the same shape as before (dict by source theater) for backward
    compatibility with existing US tracker code that consumes this output.
    The richer fields (amplifier_actor_deltas, context_notes, upstream_stressors)
    are available via the parallel _read_butterfly_bundle() helper.
    """
    try:
        from butterfly_proxy_wha import read_butterfly_signals_via_proxy
        bundle = read_butterfly_signals_via_proxy(consumer_theater='us')
        return bundle.get('upstream_fingerprints', {})
    except Exception as e:
        print(f"[US Rhetoric] Butterfly read failed: {type(e).__name__}: {e}")
        return {}


def _read_butterfly_bundle():
    """
    Read the FULL butterfly bundle (not just fingerprints) so the scan
    can consume amplifier_actor_deltas, context_notes, upstream_stressors.
    
    Returns the 4-field bundle, or an empty bundle on any failure.
    """
    try:
        from butterfly_proxy_wha import read_butterfly_signals_via_proxy
        return read_butterfly_signals_via_proxy(consumer_theater='us')
    except Exception as e:
        print(f"[US Rhetoric] Butterfly bundle read failed: {type(e).__name__}: {e}")
        return {
            'upstream_fingerprints':  {},
            'amplifier_actor_deltas': {},
            'context_notes':          [],
            'upstream_stressors':     [],
        }


def _detect_outbound_targets(actor_results, fingerprints):
    """Identify which countries the US is currently rhetoric-targeting."""
    targets = []
    target_keywords = {
        'iran':       ['iran', 'tehran', 'iranian', 'irgc'],
        'china':      ['china', 'beijing', 'chinese', 'xi jinping', 'taiwan strait'],
        'russia':     ['russia', 'putin', 'kremlin', 'russian'],
        'mexico':     ['mexico', 'sheinbaum', 'mexican', 'cartel'],
        'cuba':       ['cuba', 'cuban', 'havana', 'diaz-canel'],
        'venezuela':  ['venezuela', 'maduro', 'caracas', 'venezuelan'],
        'panama':     ['panama', 'panama canal'],
        'greenland':  ['greenland'],
        'north_korea':['north korea', 'kim jong un', 'dprk', 'pyongyang'],
        'israel':     ['israel', 'netanyahu', 'idf'],
        'lebanon':    ['lebanon', 'hezbollah'],
        'yemen':      ['yemen', 'houthi', 'houthis'],
        'ukraine':    ['ukraine', 'zelensky', 'kyiv'],
        'india':      ['india', 'modi', 'jaishankar', 'new delhi', 'h-1b', 'h1b', 'khalistan'],
    }
    exec_articles = actor_results.get('us_executive', {}).get('articles', [])
    state_articles = actor_results.get('us_state_dept', {}).get('articles', [])
    defense_articles = actor_results.get('us_defense', {}).get('articles', [])
    all_outbound = exec_articles + state_articles + defense_articles

    for target, kws in target_keywords.items():
        count = 0
        for art in all_outbound:
            text = ((art.get('title') or '') + ' ' + (art.get('description') or '')).lower()
            for kw in kws:
                if kw in text:
                    count += 1
                    break
        if count >= 2:
            targets.append({'country': target, 'mention_count': count})
    targets.sort(key=lambda t: t['mention_count'], reverse=True)
    return targets[:10]


def _write_us_fingerprint(actor_results, composite, branch_div, fracture, outbound_targets,
                          governance=None):
    """Write the US cross-theater fingerprint that all other trackers will read."""
    fingerprint = {
        'us_active':                    composite >= 26,
        'us_composite_score':           composite,
        'us_tier':                      _get_tier(composite)[0],
        'us_tier_band':                 _get_tier(composite)[2],
        'us_executive_score':           actor_results['us_executive']['actor_score'],
        'us_executive_volatility':      actor_results['us_executive']['baseline_ratio'],
        'us_dhs_enforcement_score':     actor_results['us_dhs_ice']['actor_score'],
        'us_dhs_enforcement_active':    actor_results['us_dhs_ice']['actor_score'] >= 38,
        'us_judicial_pushback_score':   actor_results['us_judicial']['actor_score'],
        'us_branch_divergence_score':   branch_div,
        'us_domestic_fracture_score':   fracture,
        'us_outbound_targets':          outbound_targets,
        # v1.4.0: us_taco_index_v0 (a permanent 0 placeholder) removed --
        # consumers read 0 as "no signal". Governance window fields added
        # (Lane B hook: other theatres can read the US political calendar).
        'us_cycle_phase':               (governance or {}).get('phase'),
        'us_political_window_open':     bool((governance or {}).get('window_open')),
        'us_governance_level':          (governance or {}).get('level'),
        'updated_at':                   datetime.now(timezone.utc).isoformat(),
    }
    _redis_set('fingerprint:us:current', fingerprint)
    return fingerprint


# ════════════════════════════════════════════════════════════════════
# MAIN SCAN
# ════════════════════════════════════════════════════════════════════

_scan_lock    = threading.Lock()
_scan_running = False


# ════════════════════════════════════════════════════════════════════
# v1.4.0 -- CANONICAL SIGNAL FIELDS
# ════════════════════════════════════════════════════════════════════
# The interpreter emits severity/category/actor_key. The WHA BLUF and the GPI
# sort and band on level/priority/theatre/pressure_type; without them every
# US signal defaulted to priority 5 and a critical cadence signal ranked with
# a low one. Severity is mapped once, here.
_SEV_TO_LEVEL    = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
_SEV_TO_PRIORITY = {'critical': 12, 'high': 10, 'medium': 7, 'low': 4}
_SEV_ICON        = {'critical': '🚨', 'high': '🔶', 'medium': '🔸', 'low': '·'}
_KINETIC_HINTS   = ('cadence', 'capability', 'dod posture', 'pre-kinetic', 'the gap',
                    'quiet preparation', 'credible buildup', 'pentagon', 'deterrence signalling',
                    'force posture', 'forces are moving')   # v1.5.0: plain-word card titles


def _canonicalize_signals(signals):
    out = []
    for sig in signals or []:
        if not isinstance(sig, dict):
            continue
        s2 = dict(sig)
        sev = str(s2.get('severity') or 'low').lower()
        s2.setdefault('level', _SEV_TO_LEVEL.get(sev, 1))
        s2.setdefault('priority', _SEV_TO_PRIORITY.get(sev, 4))
        s2.setdefault('theatre', 'us')
        s2.setdefault('icon', _SEV_ICON.get(sev, '·'))
        if 'pressure_type' not in s2:
            cat = str(s2.get('category') or '')
            txt = (str(s2.get('short_text') or '')).lower()
            if cat == 'economic':
                s2['pressure_type'] = 'economic'
            elif cat == 'foreign':
                s2['pressure_type'] = ('kinetic' if any(h in txt for h in _KINETIC_HINTS)
                                       else 'diplomatic')
            else:   # domestic / institutional / civil_social
                s2['pressure_type'] = 'governance'
        out.append(s2)
    return out


# ════════════════════════════════════════════════════════════════════
# v1.4.0 -- TWO-SIDED MOBILISATION READING
# ════════════════════════════════════════════════════════════════════
_POST_ELECTION_PHASES = ('counting', 'certification', 'lame_duck')


def _mobilization_reading(articles, phase):
    a = ACTORS['us_civil_mobilization']
    left = right = unsided = 0
    examples = {'left': [], 'right': [], 'unsided': []}
    for art in articles or []:
        text = ((art.get('title') or '') + ' ' + (art.get('description') or '')).lower()
        hit = None
        if any(k in text for k in a['keywords_left']):
            left += 1; hit = 'left'
        if any(k in text for k in a['keywords_right']):
            right += 1; hit = hit or 'right'
        if hit is None and any(k in text for k in a['keywords_unsided']):
            unsided += 1; hit = 'unsided'
        if hit and len(examples[hit]) < 3:
            examples[hit].append({'title': (art.get('title') or '')[:200],
                                  'link': art.get('link', ''), 'source': art.get('source', '')})
    window = 'results' if phase in _POST_ELECTION_PHASES else 'campaign'
    total = left + right + unsided
    if total == 0:
        read = 'No organised mobilization coverage this scan.'
    elif window == 'campaign':
        read = (f'Campaign-season mobilization: {left} left-leaning, {right} right-leaning, '
                f'{unsided} unaffiliated reports. Normal democratic activity -- context, not stress.')
    else:
        lead = ('both sides' if left and right and max(left, right) <= 2 * min(left, right)
                else 'left-leaning groups' if left > right else
                'right-leaning groups' if right > left else 'unaffiliated crowds')
        read = (f'Post-election mobilization: {left} left-leaning, {right} right-leaning, '
                f'{unsided} unaffiliated reports; carried mainly by {lead}. After Election Day, '
                f'mobilization about the results is the signal to watch near counting and '
                f'certification sites.')
    return {'left': left, 'right': right, 'unsided': unsided, 'total': total,
            'window': window, 'reading': read, 'examples': examples,
            'groups': {'left': ['No Kings', 'Indivisible', 'MoveOn', 'Lincoln Project'],
                       'right': ['Turning Point Action/USA', 'MAGA Inc.', 'Heritage Action',
                                 'Americans for Prosperity']}}


# ════════════════════════════════════════════════════════════════════
# v1.4.0 -- ELECTION-ADMINISTRATION LANE + GOVERNANCE BLOCK
# ════════════════════════════════════════════════════════════════════
# Institutional EVENTS, never partisan claims. Each class names what it is,
# the rung it can support, and its patterns. An article counts only if it
# also carries election context. Rungs above L2 need corroboration: 2+
# reports from 2+ distinct sources. L5 is never asserted from keywords.
_ELECTION_CONTEXT = ('election', 'ballot', 'vote', 'voting', 'polling', 'certif', 'canvass',
                     'midterm', 'county board', 'secretary of state', 'recount', 'concede')
ELECTION_ADMIN_CLASSES = {
    'race_calls': {
        'label': 'Race calls / concessions', 'rung': 1, 'post_election': True,
        'patterns': ['projected winner', 'race called', 'declared the winner',
                     'wins reelection', 'wins re-election',
                     'flips the seat', 'flipped the seat', 'control of the house',
                     'control of the senate'],
    },
    # v1.5.0 (Nov 4 2026): DE-ESCALATORY. Concessions and statements accepting
    # the results lower the governance read; they never raise it.
    'acceptance': {
        'label': 'Results accepted / concessions', 'rung': 0, 'post_election': True,
        'patterns': ['accept the results', 'accepts the results', 'accepted the results',
                     'accept the outcome', 'accepts the outcome', 'accept the election results',
                     'accept midterm results', 'accept the midterm results', 'accepts midterm results',
                     'accept election results',
                     'accepts election results', 'accepted the election results',
                     'concedes', 'conceded', 'concession speech', 'congratulated',
                     'congratulates', 'peaceful transfer'],
    },
    'counting': {
        'label': 'Counts still open', 'rung': 1, 'post_election': True,
        'patterns': ['too close to call', 'votes still being counted', 'ballots left to count',
                     'counting continues', 'uncalled races', 'outstanding ballots'],
    },
    # v1.4.1 Nov 1: split. Recounts exist only after a vote; election
    # litigation runs all year (voter-roll suits, ballot-rule suits).
    'recounts': {
        'label': 'Recounts / contested races', 'rung': 2, 'post_election': True,
        'patterns': ['recount', 'contested race', 'provisional ballots dispute', 'cure ballots'],
    },
    'election_litigation': {
        'label': 'Election litigation', 'rung': 2,
        'patterns': ['election lawsuit', 'sue to stop', 'ballot challenge',
                     'lawsuit over ballots', 'challenge to ballots', 'voter roll lawsuit',
                     'sues over voter rolls'],
    },
    'results_mobilization': {
        'label': 'Results-driven mobilization', 'rung': 2, 'post_election': True,
        'patterns': ['stop the count', 'count every vote', 'protest election results',
                     'protesters outside election', 'protest at counting',
                     'rally over election results'],
    },
    'certification_refusal': {
        'label': 'Certification refused or delayed', 'rung': 3, 'post_election': True,
        'patterns': ['refuse to certify', 'refused to certify', 'refuses to certify',
                     'declined to certify', 'vote against certifying', 'voted not to certify',
                     'certification delayed', 'delay certification', 'missed certification deadline',
                     'ordered to certify'],
    },
    'concession_refusal': {
        'label': 'Concession refused', 'rung': 3, 'post_election': True,
        'patterns': ['refuses to concede', 'refused to concede', 'will not concede',
                     "won't concede", 'not conceding'],
    },
    'threats_violence': {
        'label': 'Threats or violence against election officials / sites', 'rung': 3,
        'patterns': ['election official threatened', 'election officials threatened',
                     'threats against election officials', 'threats to election officials',
                     'election workers face threats', 'officials receive threats',
                     'election workers threatened', 'poll worker threatened',
                     'poll workers threatened', 'election office evacuated',
                     'bomb threat at polling', 'bomb threats', 'polling place shooting',
                     'attack on election office', 'swatting election'],
    },
    'federal_presence': {
        'label': 'Federal agents or troops at polling / counting sites', 'rung': 3,
        'patterns': ['ice at polling', 'ice agents at polling', 'federal agents at polling',
                     'federal agents polling', 'troops at polling', 'national guard at polling',
                     'agents at counting', 'seized ballots', 'seize voting machines',
                     'voting machines seized', 'federal agents seized'],
    },
}
GOV_LEVEL_LABELS = {0: 'No transition window', 1: 'Transition window -- routine',
                    2: 'Recounts or disputes under way', 3: 'Governing authority contested',
                    4: 'Multiple institutional challenges', 5: 'Transfer-of-power crisis'}
MIN_ARTICLES_FOR_GOVERNANCE = 60


# v1.4.1 Nov 1 2026 -- LIVE FALSE POSITIVE, two days BEFORE the vote: the
# card read L3 "Governing authority contested" off an Axios explainer ("Election
# cheat sheet"), a Providence Journal opinion piece ("A recount is not a
# scandal"), a lame-duck agenda story, and a court story that mentioned
# certification. Three guards:
#   1. post_election classes are closed until polls close (nothing can be
#      refused certification before anyone votes);
#   2. commentary is not an event (opinion / explainer / cheat sheet / what to
#      watch / analysis headlines are skipped);
#   3. rung-3 classes ignore copy that only references a past cycle.
_COMMENTARY_MARKERS = ('opinion', 'op-ed', 'editorial', 'explainer', 'cheat sheet',
                       'what to know', 'what to watch', 'how to', 'analysis:', 'perspective',
                       'letters to the editor', 'column:', 'podcast', 'newsletter', 'preview')
_PAST_CYCLE_RX = re.compile(r'\b(2016|2018|2020|2022|2024)\b')


def _is_commentary(title):
    t = (title or '').lower()
    return any(m in t for m in _COMMENTARY_MARKERS)


# v1.5.0 (Nov 4 2026) -- LIVE FALSE POSITIVE, the morning after: the card read
# "Contested counts: recounts / contested races" off stories saying a race
# "could head to a recount" or "may trigger an automatic recount". A recount
# that has not happened is not a contested count. A pattern preceded (within
# ~45 characters) by a hedge word is skipped and counted as hedged.
_HEDGE_RX = re.compile(r"\b(could|may|might|possible|possibly|potential|potentially|likely|if|would|"
                       r"whether|expected to|heading (?:to|for)|headed (?:to|for)|threat of|"
                       r"risk of|fears? of|calls? for|ahead of|what happens)\b")
_CONDITIONAL_RX = re.compile(r"\b(if|only if|as long as|provided|unless)\b")
_CONTROL_RX = re.compile(
    r"\b(democrats?|republicans?|gop)\b[^.;:]{0,40}?\b(win|wins|won|take|takes|took|flip|flips|flipped|"
    r"keep|keeps|kept|hold|holds|held|retain|retains|retained|capture|captures|captured|seize|seizes|seized)"
    r"\b[^.;:]{0,30}?\b(control of )?(the )?(house|senate)\b")


def _hedged(text, idx, width=45):
    return bool(_HEDGE_RX.search(text[max(0, idx - width):idx]))


def _detect_chamber_control(articles):
    """Reporting that a party WON a chamber, by distinct source. Reported,
    not certified. Hedged copy ('could win the House') is skipped."""
    out = {'house': {'democratic': set(), 'republican': set()},
           'senate': {'democratic': set(), 'republican': set()}}
    examples = {}
    for art in articles or []:
        title = art.get('title') or ''
        if _is_commentary(title):
            continue
        text = (title + ' ' + (art.get('description') or '')).lower()
        for m in _CONTROL_RX.finditer(text):
            if _hedged(text, m.start(2)) or _hedged(text, m.start()):
                continue
            party = 'democratic' if m.group(1).startswith('democrat') else 'republican'
            chamber = m.group(5)
            out[chamber][party].add(art.get('source') or 'unknown')
            examples.setdefault((chamber, party), {'title': title[:200], 'link': art.get('link', ''),
                                                   'source': art.get('source', '')})
    res = {}
    for chamber, parties in out.items():
        d, r = len(parties['democratic']), len(parties['republican'])
        winner = None
        if d >= 2 and d >= 2 * max(r, 1) and d > r:
            winner = 'democratic'
        elif r >= 2 and r >= 2 * max(d, 1) and r > d:
            winner = 'republican'
        res[chamber] = {'reported_winner': winner,
                        'sources_democratic': d, 'sources_republican': r,
                        'example': examples.get((chamber, winner)) if winner else None}
    return res


def _detect_election_administration(articles, post_election=True):
    classes = {}
    for cid, cfg in ELECTION_ADMIN_CLASSES.items():
        classes[cid] = {'label': cfg['label'], 'rung': cfg['rung'], 'count': 0,
                        'sources': set(), 'examples': [],
                        'post_election': bool(cfg.get('post_election')),
                        'open': post_election or not cfg.get('post_election')}
    skipped_commentary = 0
    hedged = 0
    for art in articles or []:
        title = art.get('title') or ''
        text = (title + ' ' + (art.get('description') or '')).lower()
        if not any(c in text for c in _ELECTION_CONTEXT):
            continue
        if _is_commentary(title):
            skipped_commentary += 1
            continue
        past_only = bool(_PAST_CYCLE_RX.search(text)) and '2026' not in text
        for cid, cfg in ELECTION_ADMIN_CLASSES.items():
            if not classes[cid]['open']:
                continue
            if cfg['rung'] >= 3 and past_only:
                continue
            hit = None
            for p in cfg['patterns']:
                i = text.find(p)
                if i < 0:
                    continue
                if cid != 'acceptance' and _hedged(text, i):
                    hedged += 1
                    continue
                hit = (p, i)
                break
            if hit:
                rec = classes[cid]
                if cid == 'acceptance':
                    tail = text[hit[1]:hit[1] + len(hit[0]) + 40]
                    if _CONDITIONAL_RX.search(tail[len(hit[0]):]) or _hedged(text, hit[1]):
                        rec['conditional'] = rec.get('conditional', 0) + 1
                        continue
                rec['count'] += 1
                rec['sources'].add(art.get('source') or 'unknown')
                if len(rec['examples']) < 3:
                    rec['examples'].append({'title': (art.get('title') or '')[:200],
                                            'link': art.get('link', ''),
                                            'source': art.get('source', '')})
    for rec in classes.values():
        rec['distinct_sources'] = len(rec['sources'])
        rec['corroborated'] = rec['count'] >= 2 and rec['distinct_sources'] >= 2
        rec['sources'] = sorted(rec['sources'])[:6]
    classes['_meta'] = {'skipped_commentary': skipped_commentary, 'post_election': post_election,
                        'skipped_hedged': hedged}
    return classes


_GOV_SO_WHAT = {
    'certification_refusal': ('A certification refusal moves a dispute from campaign rhetoric into '
                              'the machinery of government; courts have so far compelled certification '
                              '(the 2022 Cochise County precedent), so watch for court orders and compliance.'),
    'concession_refusal':    ('A refused concession in a decided race is a legitimacy signal, not a '
                              'count signal: watch whether party leadership echoes or isolates it.'),
    'threats_violence':      ('Threats against election officials are the leading indicator of '
                              'administrative strain -- resignations and evacuations slow counts, '
                              'and slow counts feed disputes.'),
    'federal_presence':      ('Federal agents or troops near polling or counting sites would test the '
                              'federal statutes that bar them there; state officials\' response is the tell.'),
    'recounts':              ('Recounts are the system working as designed; they become stress only '
                              'when paired with certification refusals or threats.'),
    'election_litigation':   ('Election lawsuits are the system working as designed; they become '
                              'stress only when paired with certification refusals or threats.'),
    'results_mobilization':  ('Results-driven crowds near counting or certification sites are the '
                              'bridge between rhetoric and physical risk.'),
}


def _governance_block(articles, cross_theater_fps, mobilization):
    """The US governance block -- GPI governance-axis contract (cf. Israel
    government_formation). Never raises; absent inputs are reported."""
    govt = None
    if _get_govt is not None:
        try:
            govt = _get_govt()
        except Exception as e:
            print(f"[US Rhetoric] composition read failed: {str(e)[:120]}")
    cyc = (govt or {}).get('election_cycle') or {}
    phase = cyc.get('phase', 'unknown' if govt is None else 'regular')
    window_open = phase in ('election_day',) + _POST_ELECTION_PHASES + ('new_congress',)
    sensed = len(articles or []) >= MIN_ARTICLES_FOR_GOVERNANCE
    # Post-election classes open once polls have closed: any post-election
    # phase, or Election Day itself (counting starts that evening).
    post_election = (phase in _POST_ELECTION_PHASES or
                     (phase == 'election_day' and cyc.get('days_until_next_election') == 0))
    classes = _detect_election_administration(articles, post_election=post_election)
    _meta = classes.pop('_meta', {})

    level = 1 if window_open else 0
    drivers = []
    for cid, rec in classes.items():
        # v1.5.0: rung-2 needs corroboration too (2+ reports, 2+ sources)
        if rec['rung'] == 2 and rec['corroborated']:
            level = max(level, 2); drivers.append(cid)
    l3 = [cid for cid, rec in classes.items() if rec['rung'] == 3 and rec['corroborated']]
    l3_single = [cid for cid, rec in classes.items() if rec['rung'] == 3 and rec['count'] >= 1
                 and not rec['corroborated']]
    if l3:
        level = max(level, 3); drivers = l3 + drivers
    elif l3_single:
        level = max(level, 2); drivers = l3_single + drivers
    if len(l3) >= 2:
        level = 4
    # L5 (transfer-of-power crisis) is never asserted from keyword counts.

    cong = (govt or {}).get('congress') or {}
    house, senate = cong.get('house') or {}, cong.get('senate') or {}
    acting = (govt or {}).get('acting_officials') or []

    if not sensed:
        headline = (f'Election-administration lane NOT SENSED ({len(articles or [])} articles; '
                    f'minimum {MIN_ARTICLES_FOR_GOVERNANCE}) -- absence of reports is not calm')
    elif level >= 3:
        headline = GOV_LEVEL_LABELS.get(level, 'Governing authority contested') + ': ' + ', '.join(
            ELECTION_ADMIN_CLASSES[c]['label'].lower() for c in drivers[:2])
    elif level == 2:
        headline = 'Recounts or disputes under way: ' + ', '.join(
            ELECTION_ADMIN_CLASSES[c]['label'].lower() for c in drivers[:2])
    elif window_open:
        headline = (f"{cyc.get('phase_label', 'Transition window')} -- no certification, "
                    f"security or federal-presence incidents corroborated")
    else:
        headline = 'No election transition window open'

    # v1.5.0 -- RESULTS PHASE: what the reporting says happened, in words.
    control = _detect_chamber_control(articles) if post_election else {}
    acc = classes.get('acceptance') or {}
    accepted = bool(acc.get('corroborated'))
    party_word = {'democratic': 'Democrats', 'republican': 'Republicans'}
    results_bits = []
    _w = {ch: (control.get(ch) or {}).get('reported_winner') for ch in ('house', 'senate')}
    if _w['house'] and _w['house'] == _w['senate']:
        results_bits.append(f"{party_word[_w['house']]} won the House and the Senate")
    else:
        for ch in ('house', 'senate'):
            if _w[ch]:
                results_bits.append(f'{party_word[_w[ch]]} won the {ch.capitalize()}')
    if sensed and level <= 1 and post_election:
        parts = []
        if results_bits:
            parts.append('Reporting says ' + ' and '.join(results_bits) + ' (called by the media, not yet certified)')
        else:
            parts.append('Results are being counted and called')
        if accepted:
            parts.append('the results are being accepted')
        parts.append('no disputes, threats or federal interference corroborated')
        headline = '; '.join(parts)
    elif sensed and post_election and results_bits:
        headline += ' | ' + '; '.join(results_bits)

    so_what = [_GOV_SO_WHAT[c] for c in drivers if c in _GOV_SO_WHAT][:3]
    # v1.5.0 -- what a change of control MEANS (reported, not yet certified)
    for ch in ('house', 'senate'):
        w = (control.get(ch) or {}).get('reported_winner')
        cur = ((house if ch == 'house' else senate).get('majority_party') or '').lower()
        if not w:
            continue
        flip = bool(cur) and not cur.startswith(w[:3])
        if ch == 'house' and flip:
            so_what.append('A change of House majority on January 3 2027 hands the incoming side the '
                           'committee gavels: subpoenas, investigations and the first word on spending. '
                           'Until then the outgoing majority governs in a lame duck, the period of least '
                           'constraint -- watch for legislation and confirmations rushed through before January.')
        elif ch == 'senate' and flip:
            so_what.append('A change of Senate majority decides confirmations from January: nominees, '
                           'judges and the posts now held in an acting capacity, and treaties.')
        elif not flip and cur:
            so_what.append(f'The {ch.capitalize()} majority is reported unchanged.')
    if accepted:
        so_what.insert(0, 'Statements accepting the results and concessions are the strongest single '
                          'de-escalation signal in the transition: they lower the odds of a certification '
                          'fight. Watch that county and state certification then follows on schedule.')
    so_what = so_what[:4]
    # LANE B hook (cross-read): the post-election window as an input to the
    # Iran ceasefire read. Context only -- never scored here.
    cross_read = None
    ir = (cross_theater_fps or {}).get('iran') if isinstance(cross_theater_fps, dict) else None
    lean = (((ir or {}).get('ceasefire_trajectory') or {}).get('lean')
            if isinstance(ir, dict) else None)
    if phase in _POST_ELECTION_PHASES and lean:
        cross_read = (f'The post-election window (until the new Congress is sworn in) is open while '
                      f'the Iran ceasefire reads "{lean}". Historically the lame duck is the period '
                      f'of least legislative constraint on the executive; read the two together.')
        if lean in ('strained', 'fraying', 'breach_risk'):
            so_what.append(cross_read)
    if acting:
        so_what.append(f'{len(acting)} senior post(s) held in an acting capacity or unverified '
                       f'({", ".join(a["role"] for a in acting[:3])}): Senate control decides how '
                       f'fast they are filled.')
    watch = ['State certification deadlines and any county-level refusals',
             'Concessions in the races that decide chamber control',
             'Threats or evacuations at election offices',
             'Speaker election on Jan 3 2027 (first vote of the new House)']
    return {
        'version':           TRACKER_VERSION,
        'phase':             phase,
        'phase_label':       cyc.get('phase_label'),
        'window_open':       window_open,
        'days_since_election': cyc.get('days_since_election'),
        'next_milestone':    cyc.get('next_milestone'),
        'next_milestone_date': cyc.get('next_milestone_date'),
        'days_to_milestone': cyc.get('days_to_milestone'),
        'level':             level,
        'level_label':       GOV_LEVEL_LABELS.get(level),
        'sensed':            sensed,
        'headline':          headline,
        'drivers':           drivers,
        'classes':           classes,
        'post_election_classes_open': post_election,
        'skipped_commentary': _meta.get('skipped_commentary', 0),
        'skipped_hedged':    _meta.get('skipped_hedged', 0),
        'reported_control':  control,
        'results_accepted':  accepted,
        'acceptance':        {'count': acc.get('count', 0), 'sources': acc.get('distinct_sources', 0),
                              'conditional': acc.get('conditional', 0)},
        'chambers': {
            'house':  {k: house.get(k) for k in ('majority_party', 'majority_size',
                                                  'minority_size', 'vacant', 'as_of')},
            'senate': {k: senate.get(k) for k in ('majority_party', 'majority_size',
                                                   'minority_size', 'as_of')},
            'configuration': ((govt or {}).get('structural_baseline') or {}).get('configuration'),
            'data_freshness': (govt or {}).get('data_freshness'),
            'staleness_warning': (govt or {}).get('staleness_warning'),
        },
        'acting_officials':  acting,
        'mobilization':      {k: mobilization.get(k) for k in ('left', 'right', 'unsided',
                                                               'window', 'reading')},
        'cross_read_iran':   cross_read,
        'so_what':           so_what,
        'watch':             watch,
        'composition_available': govt is not None,
        'disclaimer':        ('Institutional events only, corroborated above L2. Not a forecast of '
                              'any race and not a judgement on any party.'),
        'computed_at':       datetime.now(timezone.utc).isoformat(),
    }


def _governance_signal(gov):
    """Canonical GPI governance-axis signal. Category tokens 'election' /
    'governance' route it to the governance axis (GOVERNANCE_CATEGORY_HINTS)."""
    if not gov or (not gov.get('window_open') and gov.get('level', 0) < 2):
        return None
    lvl = int(gov.get('level') or 0)
    cat = 'us_election_certification' if lvl >= 2 else 'us_governance_transition'
    if not gov.get('sensed'):
        cat = 'us_governance_transition'
    return {
        'category':      cat,
        'pressure_type': 'governance',
        'theatre':       'us',
        'level':         lvl if gov.get('sensed') else 1,
        'priority':      8 + lvl,
        'severity':      {0: 'low', 1: 'low', 2: 'medium', 3: 'high', 4: 'critical'}.get(lvl, 'low'),
        'icon':          '🏛️',
        'color':         '#0d9488',
        'actor_key':     'us_governance',
        # v1.5.0: no flag emoji -- Windows renders the US flag as the letters
        # "US", so the card read "us US: ...".
        'short_text':    ('US election: ' + gov.get('headline', ''))[:230],
        'long_text':     ' '.join([gov.get('headline', '') + '.'] + (gov.get('so_what') or [])[:2])[:480],
        'source_link':   '/rhetoric-us.html#governance',
    }


# ════════════════════════════════════════════════════════════════════
# L5 RESERVATION CONTRACT (v1.0.0 — May 21 2026)
# ════════════════════════════════════════════════════════════════════
#
# CEASEFIRE_PARTNERS: theaters where US has an active diplomatic/ceasefire
# track. When kinetic L5 conditions are detected with a partner that has
# an active ceasefire (diplomatic_active=True AND ceasefire_level>=3),
# the L5 trigger is SUPPRESSED for that source. Other kinetic sources
# (or domestic) still fire normally.
#
# Today: Iran is the only active US ceasefire partner (May 21, 2026).
# Future: add 'russia', 'dprk', etc. when ceasefires emerge. The platform's
# canonical schema is consistent — diplomatic_active (bool) +
# ceasefire_level (0-5) + diplomatic_modifier (negative int) across all
# tracker fingerprints.
CEASEFIRE_PARTNERS  = ['iran']
CEASEFIRE_THRESHOLD = 3  # ceasefire_level >= 3 = framework agreed or better

# Map tier_lvl string ('L0'-'L5') to integer 0-5 for BLUF compatibility
def _us_tier_to_int(tier_str):
    """Convert tier string like 'L4' to integer 4. Defaults to 0."""
    if isinstance(tier_str, str) and tier_str.startswith('L'):
        try:
            return int(tier_str[1:])
        except (ValueError, IndexError):
            return 0
    return 0


def _compute_us_l5_gate(tier_lvl, actor_results, cross_theater_fps, outbound_targets):
    """
    Per platform L5 Reservation Contract: US L5 "Crisis" requires
    an explicit kinetic / humanitarian / economic / diplomatic L5 trigger.

    US is a command-node + anchor tracker. Real L5 events ARE possible
    (2008-class economic collapse, constitutional crisis, mass-casualty
    domestic event, active hot war). Kinetic axis gets REAL ceasefire-aware
    logic because US-Iran is in active ceasefire (May 21 2026).
    Humanitarian / Economic / Diplomatic axes scaffold for weekend audit.

    Returns dict with axis flags + reason + ceasefire-suppression transparency.
    """
    gate = {
        'kinetic':                        False,
        'humanitarian':                   False,
        'economic':                       False,
        'diplomatic':                     False,
        'reason':                         '',
        'any':                            False,
        'l5_ceasefire_suppressed_sources': [],
    }
    reasons = []

    # ── KINETIC L5 (REAL — ceasefire-aware) ──
    # Fires when US defense+executive actors at L4+ AND outbound targeting
    # specific theaters at high mention count. Per-source suppression if
    # that source has active ceasefire with US.
    defense_lvl   = _us_tier_to_int(actor_results.get('us_defense', {}).get('tier', 'L0'))
    executive_lvl = _us_tier_to_int(actor_results.get('us_executive', {}).get('tier', 'L0'))

    if defense_lvl >= 4 or executive_lvl >= 4:
        # Detect potential kinetic L5 sources (top outbound targets)
        potential_sources = []
        for target in (outbound_targets or [])[:5]:
            country  = target.get('country', '')
            mentions = target.get('mention_count', 0)
            if mentions >= 5 and country:
                potential_sources.append({
                    'source':   country,
                    'reason':   f'US defense L{defense_lvl} + executive L{executive_lvl}; {mentions} outbound mentions',
                    'mentions': mentions,
                })

        # Filter through ceasefire awareness
        kinetic_fired = []
        for src in potential_sources:
            source = src['source']
            if source in CEASEFIRE_PARTNERS:
                partner_fp = cross_theater_fps.get(source, {}) if isinstance(cross_theater_fps, dict) else {}
                if (partner_fp.get('diplomatic_active') and
                    partner_fp.get('ceasefire_level', 0) >= CEASEFIRE_THRESHOLD):
                    gate['l5_ceasefire_suppressed_sources'].append({
                        'source':           source,
                        'reason':           src['reason'],
                        'ceasefire_level':  partner_fp.get('ceasefire_level', 0),
                        'note':             f'Kinetic L5 conditions present vs {source.upper()}; suppressed by active ceasefire (level {partner_fp.get("ceasefire_level", 0)})',
                    })
                    continue
            kinetic_fired.append(src)

        # Gate fires if ANY kinetic source survived ceasefire filtering
        if kinetic_fired:
            gate['kinetic'] = True
            sources_str = ', '.join(s['source'].upper() for s in kinetic_fired)
            reasons.append(f'Kinetic: US operational posture vs {sources_str} (defense L{defense_lvl}, exec L{executive_lvl})')

    # ── HUMANITARIAN L5 (scaffold — refine in weekend audit) ──
    # Would fire on: Katrina-class disaster IDPs, mass political IDPs,
    # major famine/food crisis. No detection logic yet.
    # Today: never fires.

    # ── ECONOMIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: 2008-class systemic collapse, sovereign debt crisis,
    # mass bank failures. us_federal_reserve actor would be key signal.
    # No detection logic yet. Today: never fires.

    # ── DIPLOMATIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: mass allied PNG/embassy closure, NATO rupture,
    # constitutional crisis with foreign isolation. branch_divergence_score
    # would be key signal. No detection logic yet. Today: never fires.

    gate['any']    = any(gate[k] for k in ('kinetic', 'humanitarian', 'economic', 'diplomatic'))
    if reasons:
        gate['reason'] = '; '.join(reasons)
    elif gate['l5_ceasefire_suppressed_sources']:
        gate['reason'] = f"L5 conditions suppressed by active ceasefire(s) with: {', '.join(s['source'] for s in gate['l5_ceasefire_suppressed_sources'])}"
    else:
        gate['reason'] = 'No L5 axis trigger fired'

    return gate


def _build_us_signal_text(theatre_level, tier_band, composite, branch_div, fracture,
                           outbound_targets, l5_gate, l5_capped=False):
    """
    Build short_text + long_text for US's theatre_high signal.
    Returns dict {'short': str, 'long': str}.
    """
    label_map = {0: 'Stable', 1: 'Active', 2: 'Active+', 3: 'Volatile',
                 4: 'Volatile+', 5: 'Crisis'}
    label = label_map.get(theatre_level, 'Stable')

    # Top outbound targets
    targets_brief = ''
    if outbound_targets:
        top_3 = [t.get('country', '').upper() for t in outbound_targets[:3] if t.get('country')]
        if top_3:
            targets_brief = ', '.join(top_3)

    # Short text: prioritize ceasefire transparency if suppression fired
    suppressed = l5_gate.get('l5_ceasefire_suppressed_sources', []) if isinstance(l5_gate, dict) else []
    if suppressed:
        suppressed_brief = ', '.join(s.get('source', '').upper() for s in suppressed)
        short = f"🇺🇸 US L{theatre_level} {label} — ceasefire holding vs {suppressed_brief}"
    elif targets_brief:
        short = f"🇺🇸 US L{theatre_level} {label} — outbound focus: {targets_brief}"
    else:
        short = f"🇺🇸 US L{theatre_level} {label}"

    if len(short) > 120:
        short = short[:117] + '...'

    # Long text: full picture
    long_parts = [f"🇺🇸 US at L{theatre_level} {label} (composite score {composite}/100, band {tier_band})."]
    if branch_div is not None:
        long_parts.append(f"Branch divergence: {branch_div}.")
    if fracture is not None:
        long_parts.append(f"Domestic fracture: {fracture}.")
    if targets_brief:
        long_parts.append(f"Outbound targeting: {targets_brief}.")
    if suppressed:
        for s in suppressed:
            long_parts.append(f"⚠️ L5 conditions present vs {s.get('source', '').upper()} but suppressed by active ceasefire (level {s.get('ceasefire_level', 0)}).")
    if l5_capped:
        long_parts.append("L5 axis gate did not fire — capped at L4 ceiling per platform L5 Reservation Contract.")
    else:
        long_parts.append("US is a command-node + anchor tracker; reads outbound rhetoric and 5+ cross-theater fingerprints.")

    return {'short': short, 'long': ' '.join(long_parts)}


def run_us_rhetoric_scan(force=False):
    """Run a full US rhetoric scan. Returns the result dict."""
    global _scan_running
    with _scan_lock:
        if _scan_running and not force:
            print("[US Rhetoric] Scan already running, skipping")
            return None
        _scan_running = True

    start_time = time.time()
    print(f"[US Rhetoric] === Starting scan at {datetime.now(timezone.utc).isoformat()} ===")

    try:
        # Phase 1: fetch articles
        print("[US Rhetoric] Phase 1: fetching articles...")
        articles = _fetch_all_articles()
        print(f"[US Rhetoric] Total articles fetched: {len(articles)}")

        # Phase 2: classify by actor
        print("[US Rhetoric] Phase 2: classifying by actor...")
        actor_results = _classify_articles(articles)

        # Phase 3: composite score
        composite = _compute_composite_score(actor_results)
        tier_lvl, tier_name, tier_band, tier_icon, tier_desc = _get_tier(composite)
        print(f"[US Rhetoric] Composite score: {composite} ({tier_lvl} {tier_name} -- {tier_band})")

        # Phase 4: cross-theater reads
        print("[US Rhetoric] Phase 4: reading cross-theater fingerprints...")
        cross_theater_fps = _read_crosstheater_fingerprints()
        print(f"[US Rhetoric] Read fingerprints from {len(cross_theater_fps)} theaters")

        outbound_targets = _detect_outbound_targets(actor_results, cross_theater_fps)
        print(f"[US Rhetoric] Outbound targets detected: {[t['country'] for t in outbound_targets[:5]]}")

        # ── L5 RESERVATION CONTRACT (v1.0.0 May 21 2026) ──
        # Map tier_lvl (string 'L0'-'L5') to integer for BLUF compatibility,
        # compute L5 gate (ceasefire-aware for kinetic axis), build signal text.
        raw_theatre_level = _us_tier_to_int(tier_lvl)
        l5_gate = _compute_us_l5_gate(tier_lvl, actor_results, cross_theater_fps, outbound_targets)
        if raw_theatre_level >= 5 and not l5_gate['any']:
            theatre_level = 4
            l5_capped = True
            print(f"[US Rhetoric] L5 gate enforced: raw={raw_theatre_level} capped at L4 "
                  f"(reason: {l5_gate['reason']})")
        else:
            theatre_level = raw_theatre_level
            l5_capped = False

        # ── Build label + signal text for BLUF consumption ──
        us_label_map = {0: 'Stable', 1: 'Active', 2: 'Active+', 3: 'Volatile',
                        4: 'Volatile+', 5: 'Crisis'}
        theatre_label = us_label_map.get(theatre_level, 'Stable')

        # Phase 5: branch divergence + domestic fracture (interpreter)
        # THE JOIN (Sep 7, 2026): pull the military tracker's signed capability
        # read so rhetoric can be set against measured capability. Rhetoric
        # without movement is posturing; rhetoric against FALLING capability is
        # the gap. Neither sensor can see that alone.
        military_capability = read_military_capability('us')

        if INTERPRETER_AVAILABLE:
            branch_div = compute_branch_divergence_score(actor_results)
            fracture   = compute_domestic_fracture_score(actor_results, articles)
            top_signals = compute_top_signals(actor_results, articles, cross_theater_fps,
                                              capability=military_capability)
            so_what    = compute_so_what_factor(actor_results, composite, outbound_targets,
                                                capability=military_capability,
                                                articles=articles)
            capability_gap = compute_capability_rhetoric_gap(actor_results,
                                                             military_capability)
            if capability_gap.get('available'):
                print(f"[US Rhetoric] Capability-rhetoric join: {capability_gap['label']} "
                      f"(confidence {capability_gap['confidence']})")
            else:
                print(f"[US Rhetoric] Capability-rhetoric join not completed: "
                      f"{capability_gap.get('reason')}")
        else:
            branch_div = 0
            fracture   = 0
            top_signals = []
            so_what    = {'factor': 'unknown', 'description': 'Signal interpreter not loaded'}
            capability_gap = {'available': False, 'reason': 'interpreter_unavailable',
                              'assessment': 'Signal interpreter not loaded.'}

        # ════════════════════════════════════════════════════════════════════
        # Phase 5.5: Jawboning Primitive — fire Trump command signatures
        # ════════════════════════════════════════════════════════════════════
        # GREENFIELD wire-in (Phase 5b, May 15, 2026). Posts the full
        # actor_results to ME backend's /api/jawboning/detect, where the
        # catalog-based detector evaluates all 11 Trump command signatures
        # and writes Redis fingerprints (jawboning:command:us:on_china,
        # :on_iran, :on_rare_earths_and_critical_minerals, etc.) with 24h TTL.
        #
        # Hard-bounded by threaded timeout (25s). If the proxy hangs or fails,
        # the scan continues with empty jawboning_results — no impact on
        # composite scoring, fingerprint write, or downstream consumers.
        # Same defensive pattern as Phase 3 India strangler-fig.
        jawboning_results = {}
        jawboning_fired_count = 0
        if JAWBONING_PRIMITIVE_AVAILABLE:
            print("[US Rhetoric] Phase 5.5: jawboning primitive call...")
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _JBTimeout
            _jb_executor = ThreadPoolExecutor(max_workers=1)
            try:
                _jb_future = _jb_executor.submit(
                    detect_jawboning_via_proxy,
                    leader_id='trump',
                    country_id='us',
                    actor_results=actor_results,
                    write_fingerprints=True,    # production write — no dual-track
                    scan_id=datetime.now(timezone.utc).isoformat(),
                )
                try:
                    jawboning_results = _jb_future.result(timeout=25) or {}
                    jawboning_fired_count = sum(1 for v in jawboning_results.values() if v)
                    if jawboning_fired_count > 0:
                        fired_sigs = [k for k, v in jawboning_results.items() if v]
                        print(f"[US Rhetoric] 🦋 {jawboning_fired_count} jawboning signature(s) fired: {fired_sigs}")
                    else:
                        print(f"[US Rhetoric] No jawboning signatures fired this scan "
                              f"(0/{len(jawboning_results)} evaluated)")
                except _JBTimeout:
                    print("[US Rhetoric] ⏱️ Jawboning primitive exceeded 25s — "
                          "ABANDONING (scan continues, no fingerprints written this cycle)")
                except Exception as e:
                    print(f"[US Rhetoric] ⚠️ Jawboning primitive failed: "
                          f"{type(e).__name__}: {str(e)[:160]}")
            finally:
                _jb_executor.shutdown(wait=False)
        else:
            print("[US Rhetoric] Phase 5.5: jawboning primitive unavailable — skipping")

        # ── v1.4.0: governance block + two-sided mobilization ──
        try:
            from us_government_composition import determine_cycle_phase as _dcp
            _phase_now = _dcp().get('phase')
        except Exception:
            _phase_now = None
        mobilization = _mobilization_reading(articles, _phase_now)
        governance = _governance_block(articles, cross_theater_fps, mobilization)
        _gsig = _governance_signal(governance)
        if _gsig:
            top_signals = [_gsig] + list(top_signals or [])
        # Absence-honest: almost no articles is NOT a quiet week.
        sensed = len(articles) >= MIN_ARTICLES_FOR_GOVERNANCE
        if not sensed:
            so_what = dict(so_what or {})
            so_what['factor'] = 'Not Sensed'
            so_what['description'] = (
                f'Only {len(articles)} articles reached this scan. The scores below are a '
                f'coverage gap, not a reading of calm. Check source health before using them.')
            top_signals = [{
                'short_text': f'Coverage gap: {len(articles)} articles this scan (not sensed)',
                'long_text':  'Too few articles to read US rhetoric. Absence of signals here is '
                              'not evidence of calm.',
                'severity': 'low', 'category': 'institutional', 'actor_key': 'us_executive',
            }] + list(top_signals or [])
        # v1.5.1: the day after an election, the result IS the story. The
        # rhetoric composite measures domestic tempo, so on its own it said
        # "Active / Stable" without a word about the vote.
        if sensed and isinstance(governance, dict) \
                and governance.get('phase') in _POST_ELECTION_PHASES \
                and governance.get('headline'):
            so_what = dict(so_what or {})
            _gh = str(governance['headline']).rstrip('.')
            so_what['description'] = ('This week\'s story is the election result. ' + _gh + '. '
                                      'Day to day, the rhetoric reading below is '
                                      + (so_what.get('factor') or 'steady').lower() + ': '
                                      + (so_what.get('description') or ''))
            so_what['factor'] = 'Post-election window · ' + (so_what.get('factor') or 'Active')
            so_what['bullet_points'] = ((governance.get('so_what') or [])[:2]
                                        + list(so_what.get('bullet_points') or []))[:6]
        top_signals = _canonicalize_signals(top_signals)
        top_signals.sort(key=lambda s: -int(s.get('priority', 0) or 0))
        _redis_set('us:governance_transition', governance, ttl=7 * 24 * 3600)

        # Phase 6: write fingerprint
        fingerprint = _write_us_fingerprint(actor_results, composite, branch_div, fracture,
                                            outbound_targets, governance)

        # ── L5 Reservation Contract: build signal text now that branch_div + fracture exist ──
        signal_text = _build_us_signal_text(
            theatre_level, tier_band, composite, branch_div, fracture,
            outbound_targets, l5_gate, l5_capped,
        )

        # Phase 7: build full result
        elapsed = round(time.time() - start_time, 1)
        result = {
            'composite_score':         composite,
            'tier':                    tier_lvl,
            'tier_name':               tier_name,
            'tier_band':               tier_band,
            'tier_icon':               tier_icon,
            'tier_description':        tier_desc,

            # ── L5 Reservation Contract fields (v1.0.0 May 21 2026) ──
            'theatre_level':           theatre_level,
            'theatre_score':           composite,           # alias for BLUF compatibility
            'theatre_label':           theatre_label,
            'signal_text_short':       signal_text['short'],
            'signal_text_long':        signal_text['long'],
            'l5_gate':                 l5_gate,
            'raw_theatre_level':       raw_theatre_level,
            'l5_capped':               l5_capped,
            'source_class':            'command_node_anchor',  # US is command-node + platform anchor tracker
            'actors':                  {k: {kk: v[kk] for kk in v if kk != 'articles'}
                                        for k, v in actor_results.items()},
            'cross_theater_fps':       cross_theater_fps,
            'outbound_targets':        outbound_targets,
            'branch_divergence_score': branch_div,
            'domestic_fracture_score': fracture,
            'top_signals':             top_signals,
            'so_what':                 so_what,
            'capability_rhetoric_gap':  capability_gap,
            'military_capability':      military_capability,
            'fingerprint':             fingerprint,
            'article_count':           len(articles),
            'scan_seconds':            elapsed,
            'scan_completed_at':       datetime.now(timezone.utc).isoformat(),
            # v1.4.0: the WHA BLUF reads 'scanned_at'; it was always blank.
            'scanned_at':              datetime.now(timezone.utc).isoformat(),
            'version':                 TRACKER_VERSION,
            'success':                 True,
            'sensed':                  sensed,
            'governance':              governance,
            'mobilization':            mobilization,
            'source_counts':           _compute_source_counts(articles),
            # v1.3 - what each fetcher actually did, as opposed to whether
            # a key for it exists. See the *_available flags below, which
            # are configuration checks and are kept only for compatibility.
            'source_health':           _health_report(EXPECTED_SOURCES),
            'actor_display_order':     ACTOR_DISPLAY_ORDER,
            'layer_order':             LAYER_ORDER,
        }

        # Phase 8: cache write
        _redis_set('rhetoric:us:latest', result)
        compact = {k: result[k] for k in ('composite_score', 'tier', 'tier_name', 'tier_band',
                                          'tier_icon', 'top_signals', 'so_what',
                                          'capability_rhetoric_gap',
                                          'outbound_targets', 'scan_completed_at')}
        _redis_set('rhetoric:us:summary', compact)

        # Phase 9: history snapshot
        snapshot = {
            'date':            datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'composite_score': composite,
            'tier':            tier_lvl,
            'tier_band':       tier_band,
            'actor_scores':    {k: v['actor_score'] for k, v in actor_results.items()},
            'fracture':        fracture,
            'branch_div':      branch_div,
        }
        _redis_lpush_trim('rhetoric:us:history', snapshot, max_len=336)

        print(f"[US Rhetoric] ✅ Scan complete in {elapsed}s -- composite={composite} ({tier_lvl})")
        return result

    except Exception as e:
        print(f"[US Rhetoric] ❌ Scan error: {str(e)[:300]}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        with _scan_lock:
            _scan_running = False


# ════════════════════════════════════════════════════════════════════
# SUBREDDIT LEAN CLASSIFICATION (v1.3 — May 16, 2026)
# ════════════════════════════════════════════════════════════════════
# 5-bucket classification (left / center_left / center / center_right /
# right / far_right). The UI renders these as 3 buckets (LEFT / CENTER /
# RIGHT) but the backend keeps the granularity for future v1.2 expansion.
#
# 'apolitical' subreddits are tracked separately and shown as a footnote
# on the cross-spectrum balance card, NOT mixed into political buckets.
#
# Methodology: classifications follow the existing descriptions in
# reddit_signals_us.REDDIT_SUBS_US ("left-leaning, high volume", etc.).
# Pundit subs (Rogan/Tucker/Shapiro/Ezra/Pivot) added May 16 with
# best-effort classification based on each show's editorial posture.
# ════════════════════════════════════════════════════════════════════

SUBREDDIT_LEAN_5BUCKET = {
    # ── Explicitly political ──
    'politics':            'left',           # high-volume left
    'Conservative':        'right',          # curated right
    'moderatepolitics':    'center',         # moderated cross-spectrum
    'NeutralPolitics':     'center',         # moderated fact-based
    'NeutralNews':         'center',         # moderated fact-based

    # ── General news (cross-spectrum framing) ──
    'news':                'center',
    'worldnews':           'center',

    # ── Civil/social (incident-driven, generally non-partisan) ──
    'protest':             'center',
    'PublicFreakout':      'center',
    'scotus':              'center',
    'law':                 'center',

    # ── Pundit subs (v1.3 May 16, 2026) ──
    'JoeRogan':            'right',          # populist/contrarian right
    'TuckerCarlson':       'far_right',
    'BenShapiro':          'right',
    'EzraKleinShow':       'center_left',
    'PivotPodcast':        'center_left',

    # ── Apolitical (tracked separately, NOT in political buckets) ──
    'weather':             'apolitical',
    'TropicalWeather':     'apolitical',
    'CredibleDefense':     'apolitical',
    'warcollege':          'apolitical',
    'NationalGuard':       'apolitical',
    'economy':             'apolitical',
    'Economics':           'apolitical',
    'layoffs':             'apolitical',
    'povertyfinance':      'apolitical',
    'wallstreetbets':      'apolitical',
    'cybersecurity':       'apolitical',
    'netsec':              'apolitical',
    'sysadmin':            'apolitical',
    'OSINT':               'apolitical',
}

# Map 5-bucket → 3-bucket for UI consumption.
LEAN_5_TO_3 = {
    'left':         'left',
    'center_left':  'left',     # collapse left-leaning subs into LEFT for 3-bucket UI
    'center':       'center',
    'center_right': 'right',    # collapse right-leaning into RIGHT
    'right':        'right',
    'far_right':    'right',
}


def _compute_source_counts(articles):
    """
    Aggregate article counts by source_type for diagnostics.

    v1.3 (May 16, 2026): also computes subreddit-lean breakdown for
    the cross-spectrum balance card on rhetoric-us.html. Reads the
    'source' field on Reddit articles (format 'reddit/r/<subname>')
    and buckets by SUBREDDIT_LEAN_5BUCKET classification.

    Returns dict with these keys:
        <source_type>     — total count per source_type (rss, reddit, etc.)
        reddit_lean_5     — {left, center_left, center, center_right,
                             right, far_right, apolitical, unmapped}
        reddit_lean_3     — {left, center, right, apolitical}  (UI-friendly)
        reddit_breakdown  — {subreddit_name: count}  (for hover tooltips)
    """
    counts = {}
    # 5-bucket counters (backend granularity)
    lean_5 = {
        'left':         0,
        'center_left':  0,
        'center':       0,
        'center_right': 0,
        'right':        0,
        'far_right':    0,
        'apolitical':   0,
        'unmapped':     0,   # new subreddit not in SUBREDDIT_LEAN_5BUCKET
    }
    # Per-subreddit breakdown for hover tooltips
    breakdown = {}

    for art in articles:
        st = art.get('source_type', 'unknown')
        counts[st] = counts.get(st, 0) + 1

        # Reddit-specific classification — parse source field
        if st == 'reddit':
            source = art.get('source', '') or ''
            # Expected format: 'reddit/r/<subname>'
            if source.startswith('reddit/r/'):
                subname = source[len('reddit/r/'):].strip()
                # Increment per-sub breakdown
                breakdown[subname] = breakdown.get(subname, 0) + 1
                # Classify into lean bucket
                lean = SUBREDDIT_LEAN_5BUCKET.get(subname, 'unmapped')
                lean_5[lean] = lean_5.get(lean, 0) + 1
            else:
                # Malformed source field — log under unmapped
                lean_5['unmapped'] += 1

    # Build 3-bucket UI-friendly view by collapsing 5-bucket
    lean_3 = {'left': 0, 'center': 0, 'right': 0, 'apolitical': lean_5['apolitical']}
    for bucket_5, count in lean_5.items():
        if bucket_5 in ('apolitical', 'unmapped'):
            continue
        bucket_3 = LEAN_5_TO_3.get(bucket_5, 'center')
        lean_3[bucket_3] = lean_3.get(bucket_3, 0) + count

    counts['reddit_lean_5']    = lean_5
    counts['reddit_lean_3']    = lean_3
    counts['reddit_breakdown'] = breakdown

    return counts


# ════════════════════════════════════════════════════════════════════
# CACHE / BACKGROUND
# ════════════════════════════════════════════════════════════════════

def get_us_rhetoric_cache():
    """Return cached scan result or None."""
    return _redis_get('rhetoric:us:latest')


def _background_refresh():
    """Periodic refresh thread."""
    time.sleep(INITIAL_BOOT_DELAY_SEC)
    while True:
        try:
            print("[US Rhetoric] Background refresh starting...")
            run_us_rhetoric_scan()
        except Exception as e:
            print(f"[US Rhetoric] Background refresh error: {str(e)[:200]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_background_refresh():
    """Start the background refresh thread."""
    t = threading.Thread(target=_background_refresh, daemon=True, name='us_rhetoric_bg')
    t.start()
    print("[US Rhetoric] Background refresh thread started (initial delay 90s)")


# ════════════════════════════════════════════════════════════════════
# FLASK ENDPOINT REGISTRATION
# ════════════════════════════════════════════════════════════════════

def register_us_rhetoric_endpoints(app):
    """Register Flask endpoints for the US rhetoric tracker."""
    from flask import jsonify, request

    @app.route('/api/rhetoric/us', methods=['GET', 'OPTIONS'])
    def api_rhetoric_us():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('refresh', 'false').lower() == 'true'
            if force:
                # Trigger background scan, return cached for now
                threading.Thread(target=run_us_rhetoric_scan, daemon=True).start()
            cache = get_us_rhetoric_cache()
            if not cache:
                return jsonify({'success': False,
                                'error': 'No cached data — first scan in progress.'}), 503
            return jsonify(cache)
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/rhetoric/us/debug', methods=['GET'])
    def api_rhetoric_us_debug():
        try:
            cache = get_us_rhetoric_cache() or {}
            cross_fps = _read_crosstheater_fingerprints()
            return jsonify({
                'cache_present':       bool(cache),
                'composite_score':     cache.get('composite_score'),
                'tier':                cache.get('tier'),
                'scan_completed_at':   cache.get('scan_completed_at'),
                'article_count':       cache.get('article_count'),
                'source_counts':       cache.get('source_counts', {}),
                'source_health':       cache.get('source_health', {}),
                'cross_theater_fps_loaded': list(cross_fps.keys()),
                'actors':              list(ACTORS.keys()),
                # CONFIGURATION checks, not health. '*_available' is True
                # whenever a key or module import succeeded, whether or not
                # the source returns anything. Read 'source_health' above
                # for what actually happened. Kept for UI compatibility.
                'version':             TRACKER_VERSION,
                'redis_available':     REDIS_AVAILABLE,
                'newsapi_available':   NEWSAPI_AVAILABLE,
                'newsapi_via_gateway': _newsapi_gw is not None,
                'composition_available': _get_govt is not None,
                'governance':          cache.get('governance'),
                'brave_available':     BRAVE_AVAILABLE,
                'bluesky_available':   BLUESKY_AVAILABLE,
                'telegram_available':  TELEGRAM_AVAILABLE,
                'reddit_available':    REDDIT_AVAILABLE,
                'interpreter_available': INTERPRETER_AVAILABLE,
                'military_capability_key': MILITARY_CAPABILITY_KEY,
                'military_capability_present': bool(read_military_capability('us')),
                'scan_interval_hours': SCAN_INTERVAL_HOURS,
            })
        except Exception as e:
            return jsonify({'error': str(e)[:200]}), 500

    print("[US Rhetoric] ✅ Endpoints registered: /api/rhetoric/us, /api/rhetoric/us/debug")


print("[US Rhetoric] Module loaded.")
