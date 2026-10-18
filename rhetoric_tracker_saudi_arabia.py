"""
rhetoric_tracker_saudi_arabia.py -- Asifah Analytics ME Backend -- v2.1.0 Oct 18 2026
(v2.0.0 Oct 11 2026 matcher/gate/Mecca Pact; v1.0.0 Jul 2026)
FRICTION-TIER TRACKER with DETENTE SHIM (Iran wheel step 5, per Jun 28 scoping):
Saudi Arabia sits on the Iran wheel as friction-tier WITH an active detente track
(post-2023 Beijing-brokered normalization) -- escalatory and de-escalatory signals
run simultaneously; the shim applies downward modifiers on detente vocabulary.

SLICES (crosstheater:saudi_arabia:fingerprint): iran (friction+detente),
china (counter-BRI reverse polarity -- IMEC hub), israel (normalization drift:
Accords holdout <-> signature), us (ally anchor).

ACTORS (14): royal_court_mbs, vision2030_domestic, gcc_saudi, houthi_yemen,
  mecca_pact_turkiye, mecca_pact_pakistan, saudi_mod_airdefense, aramco_energy,
  opec_policy, iran_saudi, accords_normalization, palestinian_file, us_saudi,
  egypt_support (non-pact third party, 18 Oct 2026)
MECCA PACT: Saudi Arabia · Turkiye · Pakistan (signed Aug 2026; collective
  deterrence activated 5 Oct 2026). Turkiye is a hub (turkey_spoke block);
  Pakistan is a guarantor ACTOR, not a hub.
VECTORS (4 -- these keys ARE the saudi_arabia-stability.html gauge contract):
  kinetic_inbound, energy_infrastructure, normalization_watch, domestic_transformation
CALENDAR: Hajj window = timing MULTIPLIER on kinetic/mass-casualty tripwires
  (Black Swan doctrine: calendar factors amplify, never signal alone).
EMITS: rhetoric:saudi_arabia:latest + crosstheater:saudi_arabia:fingerprint
ENDPOINTS: /api/rhetoric/saudi_arabia (+ /debug)
Convergence, not prediction. The reader completes the inference.
"""

import os
import re
import json

MODULE_VERSION = '2.2.2'   # ONE version string -- every payload/debug field reads this
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta

import requests

# Oct 18 2026: GDELT goes ONLY through the shared gateway (v2.4.x): one
# platform-wide clock (1 request / 5.5s), a shared 15-min stand-down after
# any 429, a call budget and a shared Upstash cache. NO direct fallback: a
# direct call during a stand-down re-arms GDELT's IP block for every module.
try:
    from gdelt_gateway import gdelt_fetch_probed as _gw_fetch_probed
    _GDELT_GATEWAY = True
except ImportError:
    _gw_fetch_probed = None
    _GDELT_GATEWAY = False
    print('[KSA Rhetoric] gdelt_gateway unavailable -- GDELT disabled this process (no direct fallback, by design)')
try:
    from gdelt_trickle import register_queries as _trickle_register
except ImportError:
    _trickle_register = None

# Optional dependencies — degrade gracefully if missing
try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print("[KSA Rhetoric] ⚠️  feedparser unavailable — RSS disabled")

# Cross-tracker commodity fingerprints — read via local WHA proxy.
# Architecture note: rhetoric_tracker_saudi_arabia lives on the WHA backend, but
# commodity_tracker.py lives on the ME backend. We don't import across
# backends — instead, the WHA backend has commodity_proxy_wha.py which
# caches commodity fingerprints in WHA-local Redis with a 1-hour TTL.
# This tracker calls the WHA-local proxy endpoint (same Flask app —
# resolves over localhost or the public URL with negligible overhead).
ME_BACKEND_SELF_URL = os.environ.get(
    'ME_BACKEND_SELF_URL',
    'http://localhost:10000'  # default Render port for in-process calls
)
COMMODITY_FINGERPRINT_AVAILABLE = True  # always — we use HTTP proxy, not import

# ── Telegram (v2.1.0+) ──────────────────────────────────────────────
# Optional: absent module = no Telegram, tracker still scans RSS/GDELT.
try:
    from telegram_signals import (fetch_telegram_signals_yemen,
                                  fetch_telegram_signals_iran,
                                  get_channel_meta)
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[KSA Rhetoric] telegram_signals unavailable -- Telegram disabled")


# ════════════════════════════════════════════════════════════
# TELEGRAM SOURCE-TIER POLICY  (v2.1.0 Oct 11 2026)
#
# telegram_signals.py already classifies every channel it emits:
#   official | wire | mainstream | aggregator | aligned | state | unverified
# and its own header states the principle this block implements --
#   "an aligned channel is a primary instrument for rhetoric measurement
#    and a weak input for event confirmation, and consumers cannot tell
#    those apart without the tier field."
#
# THIS TRACKER MEASURES RHETORIC. So an Ansar Allah channel is a STRONG
# source here: when the Houthis say something about Riyadh, the saying IS
# the signal. Aligned and state tiers therefore carry near-full weight for
# ACTOR SCORING.
#
# But a TRIPWIRE is an event assertion -- 'homeland_attack' claims a thing
# happened. A tripwire fired only by channels aligned with the party making
# the claim is a CLAIM, and is labelled one rather than suppressed. See
# _check_tripwires_tiered().
#
# 'unverified' weights ZERO. Rachel's own rule in telegram_signals.py:
# "fetch normally but MUST NOT be weighted as corroboration until assessed."
# They are fetched, counted and listed, and they do not move a score.
TELEGRAM_TIER_WEIGHT = {
    'official':   1.00,   # a government saying it IS the rhetoric
    'wire':       0.95,
    'mainstream': 0.90,
    'aligned':    0.85,   # primary rhetoric instrument, weak confirmer
    'state':      0.85,
    'aggregator': 0.75,   # mixed sourcing, fast, accuracy varies
    'unverified': 0.00,   # fetched and visible; never weighted
}

# Tiers that cannot CONFIRM an event on their own.
CLAIM_ONLY_TIERS = ('aligned', 'state', 'unverified')

print("[KSA Rhetoric] Module loading...")

# Try to import signal interpreter for prose generation
try:
    from saudi_arabia_signal_interpreter import (
        build_top_signals,
        build_executive_summary,
        build_so_what_factor,
        score_alignment_drift,
        build_alignment_drift_top_signal,
    )
    KSA_INTERPRETER_AVAILABLE = True
    print("[KSA Rhetoric] ✅ Signal interpreter loaded")
except ImportError:
    KSA_INTERPRETER_AVAILABLE = False
    print("[KSA Rhetoric] ⚠️  saudi_arabia_signal_interpreter unavailable (will ship in shipment 2)")

# ============================================
# CONFIGURATION
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY       = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS                = 12
BACKGROUND_REFRESH_HOURS       = 12
INITIAL_SCAN_DELAY_SECONDS     = 90
CROSSTHEATER_FINGERPRINT_TTL_HOURS = 13   # 12h refresh + 1h buffer

REDIS_KEY_LATEST       = 'rhetoric:saudi_arabia:latest'
HISTORY_KEY            = 'rhetoric:saudi_arabia:history'   # canonical snapshot index (May 22 2026 — read by wha_regional_bluf.prose_v2)
REDIS_KEY_FINGERPRINT_AXIS         = 'rhetoric:saudi_arabia:china_axis_active'
REDIS_KEY_FINGERPRINT_CHANCAY      = 'rhetoric:saudi_arabia:chancay_pressure'
REDIS_KEY_FINGERPRINT_MINING       = 'rhetoric:saudi_arabia:mining_disruption'

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'


# ============================================
# ALERT-LEVEL THRESHOLDS (per actor)
# ============================================
# Score → alert level mapping. These are tuned for an 8-actor 4-vector model
# at typical Saudi Arabia news volume (~50-150 articles/scan). Compare to baseline
# statements_per_week in each actor definition to detect surge conditions.
def actor_alert_level(score, baseline):
    """Map a numeric actor-score to a discrete alert level using the actor's baseline."""
    if score < baseline * 0.5:
        return 'low'
    if score < baseline * 1.0:
        return 'normal'
    if score < baseline * 1.8:
        return 'elevated'
    if score < baseline * 2.8:
        return 'high'
    return 'surge'


# ============================================
# ACTOR DEFINITIONS — 8 actors total
# ============================================
ACTORS = {
    # ════════════ DOMESTIC / LEADERSHIP (3) ════════════
    'royal_court_mbs': {
        'name': 'Royal Court / MBS', 'flag': '🇸🇦', 'icon': '👑', 'color': '#e2e8f0',
        'role': 'Crown Prince statements -- the jawboning-heaviest leader signal in the Gulf',
        'description': 'MBS speeches, royal court decrees, succession signals, foreign-policy declarations. Leader-signal tempo historically moves markets and diplomacy alike.',
        'vector': 'domestic_transformation',
        'keywords': ['mohammed bin salman','mbs saudi','crown prince saudi','saudi royal court','king salman',
                     'saudi royal decree','saudi succession','royal order saudi',
                     'محمد بن سلمان','ولي العهد','الديوان الملكي'],
        'baseline_statements_per_week': 8,
    },
    'vision2030_domestic': {
        'name': 'Vision 2030 / Domestic', 'flag': '🇸🇦', 'icon': '🏗️', 'color': '#a855f7',
        'role': 'Giga-projects, economic transformation, social reform signals',
        'description': 'NEOM, PIF deployments, social-reform decrees, austerity/re-scoping news. Transformation-stress signals (project delays, budget cuts) read as domestic pressure.',
        'vector': 'domestic_transformation',
        'keywords': ['vision 2030','neom','saudi pif','public investment fund saudi','giga project saudi',
                     'saudi reform','neom delay','saudi budget','saudi unemployment','رؤية 2030','نيوم'],
        'baseline_statements_per_week': 6,
    },
    'gcc_saudi': {
        'name': 'GCC / Regional Posture', 'flag': '🕌', 'icon': '🤝', 'color': '#84cc16',
        'role': 'Riyadh\'s GCC leadership line -- cohesion and rift signals',
        'description': 'Saudi statements on GCC unity, Qatar/UAE/Bahrain relations, summit outcomes. Rift vocabulary here doubles as GCC-cohesion pressure (2017 blockade precedent).',
        'vector': 'normalization_watch',
        'keywords': ['gcc summit','gulf cooperation council saudi','saudi qatar relations','saudi uae relations',
                     'saudi bahrain','alula agreement','gcc unity','مجلس التعاون'],
        'baseline_statements_per_week': 4,
    },
    # ════════════ KINETIC / SECURITY (2) ════════════
    'houthi_yemen': {
        'name': 'Houthi / Yemen Front', 'flag': '🇾🇪', 'icon': '🚀', 'color': '#dc2626',
        'role': 'Kinetic-inbound driver -- drones, missiles, ceasefire state',
        'description': 'Houthi claims and attacks toward Saudi territory + Yemen truce/ceasefire signals. The 2019-2022 record (Abqaiq, Jeddah, Abha) is the older precedent; the Oct 2026 Riyadh airport strikes are the current set.',
        'vector': 'kinetic_inbound',
        # RETARGETED 11 Oct 2026. Every term below is traceable to a verbatim
        # published headline from the Oct 8-11 2026 strike cycle:
        #   "Saudi Arabia reopens Riyadh airport after Houthi attack kills three" (Al Jazeera)
        #   "Attack on Saudi airport kills 3 as Iran-backed Houthis warn of long conflict" (CNN)
        #   "12 killed in Saudi Arabia airport attack, underscoring peril in Houthi strikes" (WaPo)
        #   "World condemns deadly Houthi attack on Saudi Arabia's Riyadh airport" (Al Jazeera)
        # v1.0.0's set named ABHA -- the 2019-2022 target -- and never named
        # RIYADH AIRPORT, which is the 2026 one. A tracker keyworded to the
        # last war reads the current one as quiet.
        'keywords': ['houthi saudi', 'houthi attack saudi', 'houthi drone saudi',
                     'houthi missile saudi', 'houthi strike saudi',
                     'houthi riyadh', 'riyadh airport attack', 'saudi airport attack',
                     'king khalid airport', 'abha airport attack', 'jizan attack',
                     'yemen ceasefire', 'yemen truce', 'houthi claim',
                     'ansar allah saudi', 'iran-backed houthis', 'houthi salvo',
                     'الحوثي', 'أنصار الله', 'مطار الرياض'],
        'baseline_statements_per_week': 6,
    },
    # ════════════════════════════════════════════════════════════
    # MECCA PACT GUARANTORS  (new 11 Oct 2026)
    #
    # The Mecca Joint Defence Agreement (Saudi Arabia / Turkiye / Pakistan,
    # signed Aug 2026) changed the attribution problem. Before it, a Houthi
    # strike on Riyadh was a Saudi-Iran bilateral. On 5 Oct 2026 the
    # signatories agreed to activate collective deterrence and a Saudi
    # deployment, and met in Riyadh over the escalating attacks.
    #
    # THE FALSIFIER IS THE POINT. These actors exist to measure whether the
    # guarantors' RHETORIC MOVES when the pact is tested. If Turkish and
    # Pakistani tempo stays flat through a mass-casualty strike on Riyadh,
    # the pact is paper -- and that is a finding, not an absence. An actor
    # that can only detect activation can only ever confirm the pact.
    #
    # Keywords from verbatim Oct 2026 headlines:
    #   "Turkiye, Pakistan agree Saudi Arabia military deployment under Mecca pact" (Al Jazeera)
    #   "Mecca defense pact signatories meeting in Riyadh over escalating Houthi attacks" (JPost)
    #   "Mecca alliance agrees to activate collective deterrence measures" (Al Jazeera)
    'mecca_pact_turkiye': {
        'name': 'Mecca Pact / Turkiye', 'flag': '\U0001F1F9\U0001F1F7', 'icon': '\U0001F91D', 'color': '#f97316',
        'role': 'Guarantor response -- does Ankara move when the pact is tested',
        'description': 'Turkish signals under the Mecca Joint Defence Agreement: deployment language, collective-deterrence vocabulary, basing and overflight. Turkiye is a HUB on this platform, so an active reading here also lights the Turkey wheel\'s Saudi spoke.',
        'vector': 'guarantor_response',
        'keywords': ['mecca pact turkiye', 'mecca pact turkey', 'turkiye saudi deployment',
                     'turkey saudi deployment', 'turkiye saudi defence', 'turkish troops saudi',
                     'mecca joint defence', 'mecca defense pact', 'mecca alliance',
                     'collective deterrence saudi', 'ankara riyadh defence',
                     # Turkish -- Ankara's own reporting, same reasoning as the
                     # Urdu set on mecca_pact_pakistan. Kept deliberately SHORT:
                     # these are transliterations of terms seen in Turkish-language
                     # coverage of the pact, and the list stays minimal until it
                     # has been validated against verbatim Turkish headlines the
                     # way the Urdu set was.
                     'mekke savunma', 'mekke anlasmasi', 'ortak savunma suudi'],
        'baseline_statements_per_week': 2,
    },
    'mecca_pact_pakistan': {
        'name': 'Mecca Pact / Pakistan', 'flag': '\U0001F1F5\U0001F1F0', 'icon': '\U0001F91D', 'color': '#22c55e',
        'role': 'Guarantor response -- does Islamabad move when the pact is tested',
        'description': 'Pakistani signals under the Mecca Joint Defence Agreement: troop deployment to Saudi Arabia, collective-deterrence activation, nuclear-umbrella vocabulary. Pakistan is NOT a hub on this platform -- it is a guarantor actor, and stays one until a Pakistan tracker drives it.',
        'vector': 'guarantor_response',
        # URDU ADDED 11 Oct 2026. Pakistan's own reporting on the pact runs in
        # Urdu, and the authoritative voice is DG ISPR -- the Army spokesman --
        # not an English wire. Every term below is traceable to a verbatim
        # published Urdu headline:
        #   "مکہ دفاعی معاہدہ: پاکستانی فوجی دستے سعودی عرب میں موجود ہیں، ڈی جی آئی ایس پی آر"
        #       (Mecca Defence Agreement: Pakistani troops ARE PRESENT in
        #        Saudi Arabia — DG ISPR)  — Aaj / Hotline News
        #   "سعودی عرب کا دفاع مکہ معاہدے کا بنیادی مقصد ہے، دفاع کریں گے: ترجمان پاک فوج"
        #       (Defending Saudi Arabia is the Mecca agreement's core purpose,
        #        and we will defend it — Pakistan Army spokesman)  — Shafaqna / Aaj
        #   "پاکستان اور سعودی عرب کا مکہ مشترکہ دفاعی معاہدے پر تعاون جاری رکھنے کا عزم"
        #       — Geo Urdu
        #
        # ⚠ THAT FIRST HEADLINE IS ITSELF A FINDING. Pakistan has publicly
        # confirmed troops are IN Saudi Arabia under the pact. The guarantor
        # has moved -- this actor is not measuring a hypothetical.
        'keywords': ['mecca pact pakistan', 'pakistan saudi deployment', 'pakistani troops saudi',
                     'pakistan saudi defence', 'pakistan saudi defense', 'islamabad riyadh defence',
                     'mecca joint defence', 'strategic mutual defence agreement',
                     'pakistan collective deterrence', 'dg ispr saudi',
                     # Urdu
                     '\u0645\u06a9\u06c1 \u062f\u0641\u0627\u0639\u06cc \u0645\u0639\u0627\u06c1\u062f\u06c1',          # Mecca defence agreement
                     '\u0645\u06a9\u06c1 \u0645\u0634\u062a\u0631\u06a9\u06c1 \u062f\u0641\u0627\u0639\u06cc',          # Mecca joint defence
                     '\u0645\u06a9\u06c1 \u0645\u0639\u0627\u06c1\u062f\u06c1',                                              # Mecca agreement
                     '\u067e\u0627\u06a9\u0633\u062a\u0627\u0646\u06cc \u0641\u0648\u062c\u06cc \u062f\u0633\u062a\u06d2',  # Pakistani troop contingents
                     '\u067e\u0627\u06a9 \u0641\u0648\u062c \u062f\u0633\u062a\u06d2',                                      # Pak Army contingents
                     # v2.1.0 Oct 18 2026: DG ISPR fixed -- 11 Oct had a stray
                     # space ('...\u0627\u06cc \u0633...' = "ای س") so it could never match.
                     '\u0688\u06cc \u062c\u06cc \u0622\u0626\u06cc \u0627\u06cc\u0633 \u067e\u06cc \u0622\u0631',       # DG ISPR
                     '\u062a\u0631\u062c\u0645\u0627\u0646 \u067e\u0627\u06a9 \u0641\u0648\u062c',                        # Pak Army spokesman
                     # v2.1.0: the 11 Oct set all hinged on Mecca (\u0645\u06a9\u06c1); Pakistani
                     # press mostly says "Pak-Saudi defence agreement". Verbatim:
                     #   "\u067e\u0627\u06a9 \u0633\u0639\u0648\u062f\u06cc \u062f\u0641\u0627\u0639\u06cc \u0645\u0639\u0627\u06c1\u062f\u06c1 \u0637\u0648\u06cc\u0644 \u0627\u0644\u0645\u062f\u062a\u06cc \u062a\u0639\u0627\u0648\u0646 \u06a9\u0627 \u0639\u06a9\u0627\u0633 \u06c1\u06d2" -- Jang
                     # Order-free substring parts: \u067e\u0627\u06a9 also catches \u067e\u0627\u06a9\u0633\u062a\u0627\u0646.
                     '\u067e\u0627\u06a9 \u0633\u0639\u0648\u062f\u06cc \u062f\u0641\u0627\u0639\u06cc',                    # Pak Saudi defence
                     '\u0628\u0627\u06c1\u0645\u06cc \u062f\u0641\u0627\u0639\u06cc \u0645\u0639\u0627\u06c1\u062f',        # mutual defence agreement (SMDA)
                     '\u0645\u0634\u062a\u0631\u06a9\u06c1 \u062f\u0641\u0627\u0639 \u067e\u0627\u06a9\u0633\u062a\u0627\u0646'],  # joint defence + Pakistan (Geo)
        'baseline_statements_per_week': 2,
    },

    # NEW 18 Oct 2026 (Rachel's ruling): Egypt is NOT a Mecca Pact signatory,
    # but it is the one outside power visibly moving -- National Defense
    # Council approval, El-Sisi's "any measure" pledge, C-130s at King Fahd
    # Air Base (Taif), parliament approving troops. It sits on the
    # guarantor_response vector, whose question was always "does an attack on
    # Saudi Arabia pull in third parties" -- but it is kept OUT of the pact's
    # own reading, so the page can say the finding plainly: the guarantors
    # are flat while a non-signatory deploys. Keywords trace to verbatim Oct
    # 2026 headlines:
    #   "Egypt Deploys Troops To Saudi Arabia"                         (Kurdistan24)
    #   "Egypt approves sending troops to Saudi amid Houthi attacks"   (Siasat)
    #   "Egypt's president vows to use 'any measure' to defend Saudi Arabia" (Fortune)
    #   "Egypt pledges support for Saudi Arabia as Houthis warn Cairo" (The National)
    #   "Egypt's Sisi seeks authorisation for defence assistance to Saudi Arabia" (Al Jazeera)
    #   "Egypt says ready to give Saudi Arabia necessary support"      (Al-Monitor)
    # Deliberately NOT 'egypt support saudi': Saudi deposits and aid TO Egypt
    # are a standing story and would read as Egypt mobilising.
    'egypt_support': {
        'name': 'Egypt (Non-Pact Support)', 'flag': '\U0001F1EA\U0001F1EC', 'icon': '\U0001F6E1\uFE0F', 'color': '#eab308',
        'role': 'Third-party military support -- not a Mecca Pact signatory',
        'description': 'Egyptian military support to Saudi Arabia outside the Mecca Pact: defence-council approval, troop and air-defence deployment, parliamentary authorisation. Read against the pact guarantors: an outsider moving while the guarantors stay flat is itself the finding.',
        'vector': 'guarantor_response',
        'keywords': ['egypt troops saudi', 'egyptian troops saudi', 'egyptian forces saudi',
                     'egypt defend saudi', 'egypt pledges support saudi',
                     'egypt necessary support saudi', 'egypt defence assistance saudi',
                     'egypt defense assistance saudi', 'egyptian military transport saudi',
                     'egyptian parliament troops', 'egypt national defense council saudi',
                     'sisi defend saudi',
                     '\u0642\u0648\u0627\u062a \u0645\u0635\u0631\u064a\u0629',     # AR  Egyptian forces
                     '\u0645\u0635\u0631 \u0627\u0644\u062f\u0641\u0627\u0639 \u0639\u0646 \u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629'],  # AR  Egypt + defend + Saudi
        'baseline_statements_per_week': 2,
    },

    'saudi_mod_airdefense': {
        'name': 'Saudi MOD / Air Defense', 'flag': '🇸🇦', 'icon': '🛡️', 'color': '#f97316',
        'role': 'Defense posture -- intercepts, coalition ops, procurement',
        'description': 'Saudi military statements: Patriot/THAAD intercepts, coalition operations, defense procurement, exercise tempo. Intercept-announcement surges track inbound-threat cycles.',
        'vector': 'kinetic_inbound',
        'keywords': ['saudi air defense','saudi intercepts','saudi military','saudi defense ministry',
                     'saudi patriot','saudi thaad','saudi coalition yemen','saudi armed forces',
                     'royal saudi air force','الدفاع الجوي السعودي'],
        'baseline_statements_per_week': 5,
    },
    # ════════════ ENERGY (2) ════════════
    'aramco_energy': {
        'name': 'Aramco / Energy Infrastructure', 'flag': '🛢️', 'icon': '⚡', 'color': '#fb923c',
        'role': 'Energy-infrastructure signal source -- facilities, throughput, threats',
        'description': 'Aramco operations + infrastructure security: Abqaiq-class facility news, East-West Petroline/Yanbu throughput (the Hormuz bypass), IMEC corridor milestones. The Apr 2026 pipeline strikes are the live precedent.',
        'vector': 'energy_infrastructure',
        'keywords': ['aramco','abqaiq','saudi pipeline','east-west pipeline','petroline','yanbu terminal',
                     'saudi oil facility','jubail','ras tanura','saudi refinery attack','imec corridor',
                     'saudi oil infrastructure','أرامكو'],
        'baseline_statements_per_week': 7,
    },
    'opec_policy': {
        'name': 'OPEC+ Policy Voice', 'flag': '🛢️', 'icon': '📊', 'color': '#eab308',
        'role': 'Production-policy rhetoric -- cuts, quotas, Russia coordination',
        'description': 'Saudi OPEC+ statements: voluntary cuts, quota disputes, ministerial outcomes. Policy-rhetoric surges historically precede production decisions that move Brent.',
        'vector': 'energy_infrastructure',
        'keywords': ['opec saudi','opec+ meeting','saudi production cut','saudi oil policy','opec quota',
                     'saudi energy minister','abdulaziz bin salman','voluntary cut'],
        'baseline_statements_per_week': 5,
    },
    # ════════════ THE WHEELS / EXTERNAL (3) ════════════
    'iran_saudi': {
        'name': 'Iran (Saudi File)', 'flag': '🇮🇷', 'icon': '⚖️', 'color': '#0ea5e9',
        'role': 'Friction wheel WITH detente shim -- escalation and normalization at once',
        'description': 'Iran-Saudi signals both directions: threats and incidents (friction) alongside embassy/hajj/trade normalization (detente, Beijing 2023 track). The shim scores detente vocabulary as de-escalatory.',
        'vector': 'kinetic_inbound',
        'keywords': ['iran saudi','saudi iran relations','iran threatens saudi','iran saudi talks',
                     'saudi embassy tehran','iran hajj','iran saudi normalization','iran saudi detente',
                     'iran attack saudi','إيران السعودية'],
        'baseline_statements_per_week': 6,
    },
    'accords_normalization': {
        'name': 'Israel Normalization Watch', 'flag': '🤝', 'icon': '🕊️', 'color': '#38bdf8',
        'role': 'Accords drift axis: holdout <-> signature',
        'description': 'Saudi-Israel normalization signals: official statements, preconditions (Palestinian state language), US-brokered package news. Each signal moves the drift read on the axis KSA has NOT yet crossed.',
        'vector': 'normalization_watch',
        # 11 Oct 2026: the defence-transfer terms are here as well as in the
        # israel_defense_transfer tripwire. The tripwire alone moved the axis
        # score but left this ACTOR flat, so a transfer story read as pure
        # kinetics and the normalization card stayed quiet through the one
        # event judged capable of forcing the hand.
        'keywords': ['saudi israel normalization','saudi abraham accords','saudi israel relations',
                     'saudi normalization deal','israel saudi talks','saudi palestinian state condition',
                     'saudi israel flights',
                     'israel air defense saudi','israeli systems saudi','israel arms saudi',
                     'israel saudi defense cooperation','israel saudi defence',
                     'التطبيع'],
        'baseline_statements_per_week': 4,
    },
    # ════════════════════════════════════════════════════════════
    # THE HOLDOUT ANCHORS, MADE CONCRETE  (new 11 Oct 2026)
    #
    # Rachel's ruling, 11 Oct 2026: "continue to track what's happening in
    # Gaza, West Bank, and even Lebanon as KSA's reasons to abstain from the
    # Accords."
    #
    # v1.0.0 modelled the holdout side as 'Palestinian-file preconditions' --
    # a PHRASE, with no actor measuring it. The drift axis therefore netted a
    # measured inroad against an unmeasured anchor, which can only ever drift
    # one way. This actor is the counterweight, and it is deliberately a
    # SEPARATE actor rather than more keywords on accords_normalization:
    # Riyadh talking about Gaza and Riyadh talking about signature are
    # opposite-polarity signals and must never land in the same bucket.
    #
    # Reads from Saudi statements ABOUT these files -- the country gate means
    # a Gaza story that never mentions Saudi Arabia does not score here.
    'palestinian_file': {
        'name': 'Palestinian File / Holdout Anchors', 'flag': '\U0001F1F5\U0001F1F8', 'icon': '\u2693', 'color': '#a855f7',
        'role': 'Accords COUNTERWEIGHT -- Riyadh\'s stated reasons to abstain',
        'description': 'Saudi statements on Gaza, the West Bank and Lebanon -- the files Riyadh names as preconditions for normalization. Hardening language re-anchors holdout; softening or silence is the signature-adjacent tell. Opposite polarity to accords_normalization by construction.',
        'vector': 'normalization_watch',
        'keywords': ['saudi gaza', 'saudi palestinian state', 'saudi west bank',
                     'saudi annexation', 'saudi two-state', 'saudi lebanon',
                     'riyadh gaza', 'saudi palestinian statehood',
                     'saudi condemns israel', 'saudi ceasefire gaza',
                     'kingdom palestinian', 'saudi arab peace initiative',
                     '\u063a\u0632\u0629', '\u0641\u0644\u0633\u0637\u064a\u0646'],
        'baseline_statements_per_week': 5,
    },

    'us_saudi': {
        'name': 'US-Saudi Track', 'flag': '🇺🇸', 'icon': '🛡️', 'color': '#64748b',
        'role': 'Ally anchor -- security guarantees, arms, strategic pacts',
        'description': 'US-Saudi statements: defense-pact negotiations, arms packages, security-guarantee language, presidential visits. The security-guarantee question couples directly to the normalization file.',
        'vector': 'normalization_watch',
        'keywords': ['us saudi','saudi defense pact','us saudi security','saudi arms deal us',
                     'biden saudi','trump saudi','us saudi agreement','saudi f-35','american troops saudi'],
        'baseline_statements_per_week': 5,
    },
}

# Helper sets for downstream classification logic
DOMESTIC_ACTORS = ['royal_court_mbs', 'vision2030_domestic', 'saudi_mod_airdefense', 'aramco_energy', 'opec_policy', 'gcc_saudi']
EXTERNAL_ACTORS = ['houthi_yemen', 'iran_saudi', 'accords_normalization', 'us_saudi']
RESOURCE_ACTORS = ['aramco_energy', 'opec_policy']
ALIGNMENT_ACTORS = {'accords_normalization': 'normalization_watch', 'us_saudi': 'normalization_watch'}

# Vector groupings -- these keys ARE the saudi_arabia-stability.html gauge contract
VECTOR_GROUPS = {
    'kinetic_inbound':         ['houthi_yemen', 'saudi_mod_airdefense', 'iran_saudi'],
    'energy_infrastructure':   ['aramco_energy', 'opec_policy'],
    'normalization_watch':     ['accords_normalization', 'us_saudi', 'gcc_saudi'],
    'domestic_transformation': ['royal_court_mbs', 'vision2030_domestic'],
    # NEW 11 Oct 2026. The question the Mecca Pact creates: does an attack on
    # Saudi Arabia pull in third parties, and do the guarantors' words move
    # before their forces do? Flat guarantor tempo through a mass-casualty
    # strike is a REAL READING -- the pact is paper -- not a missing sensor.
    'guarantor_response':      ['mecca_pact_turkiye', 'mecca_pact_pakistan', 'egypt_support'],
}

# ⚠ FIFTH VECTOR. saudi_arabia-stability.html renders a FOUR-gauge contract.
# guarantor_response is emitted in vector_scores/vector_levels but will not
# appear on that page until its gauge row is extended -- it is absent from
# the page, not absent from the data, and the rhetoric page reads the dict
# dynamically so it shows up there immediately.


# ============================================
# TRIPWIRES — high-severity events that escalate alert level regardless of volume
# ============================================
TRIPWIRES = {
    'infrastructure_strike': {
        'patterns': ['abqaiq attack','aramco facility attack','saudi pipeline attack','east-west pipeline strike',
                     'saudi refinery struck','jubail attack','ras tanura attack','yanbu attack',
                     # v2.1.3: verbatim live headlines that fired nothing --
                     #   "Iran-backed Houthis strike Saudi oil company Aramco's headquarters" (AP)
                     #   "Houthis strike Aramco hours after Saudi-led coalition hits Sanaa oil site" (Al Jazeera)
                     # Verb-anchored to the Houthis so explainers ("How Saudi Aramco
                     # restores operations after attacks") stay out.
                     'houthi strike aramco', 'houthi attack aramco', 'houthi drone aramco',
                     'houthi missile aramco'],
        'severity': 'surge',
        'note': 'Abqaiq-class energy-infrastructure strike -- the 2019 precedent halved output in a day.',
    },
    'houthi_salvo': {
        # RETARGETED 11 Oct 2026 alongside the actor keywords. The v1.0.0 set
        # named Jeddah and Abha -- the 2019-2022 targets -- and never Riyadh
        # airport, which is the Oct 2026 one.
        'patterns': ['houthi missile riyadh', 'houthi drone attack saudi',
                     'missiles fired saudi', 'drone swarm saudi',
                     'houthi attack jeddah', 'houthi attack abha',
                     'riyadh airport attack', 'saudi airport attack',
                     'king khalid airport attack', 'houthi salvo saudi',
                     'houthi strike riyadh', 'missiles riyadh',
                     # v2.2.0: irregular past tense -- "King Fahd Air Base
                     # struck by Houthi drones" fired nothing.
                     'houthi drone struck', 'houthi missile struck',
                     'houthi drone strike'],
        'severity': 'high',
        'note': 'Kinetic-inbound salvo on Saudi territory.',
    },
    'hormuz_closure': {
        'patterns': ['hormuz closed','strait of hormuz closure','hormuz blocked','iran closes hormuz'],
        'severity': 'surge',
        'note': 'Chokepoint closure -- activates the Petroline/Yanbu bypass story platform-wide.',
    },
    'accords_signature': {
        'patterns': ['saudi signs abraham accords','saudi israel normalization deal','saudi israel agreement signed',
                     'saudi recognizes israel','normalization announced saudi'],
        'severity': 'elevated',
        'note': 'THE normalization milestone -- the drift axis crossing. De-escalatory for the region, seismic for the map.',
    },
    # ADDED 11 Oct 2026, per Rachel's ruling: the one thing she judges could
    # force the Accords -- "unless KSA needs some kind of defense/weapons from
    # Israel to a degree that it forces their hand".
    #
    # This is not speculative: it is the UAE's documented path. The UAE took
    # Israeli air-defence help under fire, and this platform already tracks it
    # as israel_uae_axis ("Israeli training and air-defense transfers"). With
    # Houthi missiles reaching Riyadh and the Mecca Pact activating, the same
    # road exists for Riyadh -- and capability arriving under fire is a far
    # stronger signature-track driver than any summit.
    #
    # DELIBERATELY NOT severity 'surge': a transfer is an inroad accelerant on
    # the Accords axis, not a kinetic L5 event.
    'israel_defense_transfer': {
        'patterns': ['israel air defense saudi', 'israeli systems saudi',
                     'israel arms saudi', 'saudi israeli interceptors',
                     'israel defense deal saudi', 'israeli radar saudi',
                     'israel saudi defense cooperation',
                     # v2.1.0 Oct 18 2026: live miss -- "Trump: Israel helping
                     # Saudi Arabia against Houthis, normalization closer than
                     # ever". Verb-anchored (help/assist/defend) so that
                     # "Israel strikes Houthi port as Saudi watches" stays out.
                     'israel helping saudi', 'israel helps saudi',
                     'israel assisting saudi', 'israel assist saudi',
                     'israeli help saudi', 'israel defending saudi',
                     'israel defend saudi', 'israeli intercept saudi'],
        'severity': 'high',
        'note': ('Israeli defence capability moving toward Riyadh under kinetic '
                 'pressure. The UAE precedent: capability arriving under fire '
                 'normalizes faster than any summit. Strong INROAD driver on '
                 'the Accords axis -- it is the scenario in which the holdout '
                 'becomes materially expensive.'),
    },
    # NEW 18 Oct 2026: an outside power's forces ARRIVING in the Kingdom.
    # Sentence-scoped (tripwire matcher), so "Egypt pledges support" alone
    # does not fire -- arrival/deployment vocabulary does.
    'non_pact_deployment': {
        'patterns': ['egypt deploys troops saudi', 'egyptian troops arrive saudi',
                     'egyptian forces arrive saudi', 'egyptian military transport saudi',
                     'egypt approves sending troops saudi', 'egyptian troops deployed saudi'],
        'severity': 'elevated',
        'note': ('A non-signatory deploying forces into the Kingdom. Read against the '
                 'Mecca Pact guarantors: an outsider arriving first re-prices what the '
                 'pact is worth.'),
    },
    'succession_event': {
        # v2.2.0: STRICT PHRASES ONLY. Even sentence-scoping cannot save a
        # pattern like 'new saudi king' from "NEW: Saudi King Fahd Air Base
        # struck" -- one sentence, all three tokens, no succession. A false
        # succession signal is the most market-moving and diplomatically
        # loaded claim this tracker can make, so it fires only on formulaic
        # succession language that a facility name cannot assemble.
        'patterns': ['"king salman dies"', '"king salman has died"', '"death of king salman"',
                     '"king salman passed away"', '"mbs becomes king"',
                     '"crown prince becomes king"', '"proclaimed king"',
                     '"sworn in as king"', '"new king of saudi arabia"',
                     '"saudi succession crisis"', '"allegiance council"',
                     '\u0648\u0641\u0627\u0629 \u0627\u0644\u0645\u0644\u0643 \u0633\u0644\u0645\u0627\u0646',   # death of King Salman
                     '\u0647\u064a\u0626\u0629 \u0627\u0644\u0628\u064a\u0639\u0629'],                              # Allegiance Council
        'severity': 'high',
        'note': 'Royal succession event -- domestic-transformation rupture watch.',
    },
    'detente_rupture': {
        'patterns': ['saudi iran talks collapse','iran saudi relations severed','saudi recalls ambassador iran',
                     'iran saudi rupture','saudi cuts ties iran'],
        'severity': 'high',
        'note': 'Detente-shim rupture -- friction tier loses its brake.',
    },
    'hajj_mass_casualty': {
        'patterns': ['hajj stampede','hajj attack','mecca attack','hajj disaster','pilgrims killed mecca'],
        'severity': 'surge',
        'note': 'Custodian-legitimacy event. NOTE: Hajj-window timing is a calendar MULTIPLIER on other tripwires, never a standalone signal (Black Swan doctrine).',
    },
}
RSS_FEEDS = {
    'gn_en':   {'url': 'https://news.google.com/rss/search?q=Saudi%20Arabia%20(MBS%20OR%20Aramco%20OR%20Houthi%20OR%20Iran)&hl=en-US&gl=US&ceid=US:en', 'name': 'GoogleNews-EN', 'weight': 0.85, 'language': 'en'},
    'gn_ar':   {'url': 'https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B3%D8%B9%D9%88%D8%AF%D9%8A%D8%A9&hl=ar&gl=SA&ceid=SA:ar', 'name': 'GoogleNews-AR', 'weight': 0.8, 'language': 'ar'},
    # v2.1.0 Oct 18 2026: Urdu source. The mecca_pact_pakistan Urdu keywords
    # (11 Oct) had NO Urdu feed to match against -- GoogleNews-AR is Arabic
    # script but not Urdu vocabulary, and the Pakistani Telegram channels post
    # in English. Query is the Urdu name for Saudi Arabia, Pakistan edition.
    'gn_ur':   {'url': 'https://news.google.com/rss/search?q=%D8%B3%D8%B9%D9%88%D8%AF%DB%8C%20%D8%B9%D8%B1%D8%A8&hl=ur&gl=PK&ceid=PK:ur', 'name': 'GoogleNews-UR', 'weight': 0.8, 'language': 'ur'},
    'arabnews':{'url': 'https://www.arabnews.com/rss.xml', 'name': 'Arab News', 'weight': 1.0, 'language': 'en'},
    'saudigaz':{'url': 'https://saudigazette.com.sa/rssFeed/74', 'name': 'Saudi Gazette', 'weight': 0.95, 'language': 'en'},
    'alarabiya':{'url': 'https://www.alarabiya.net/feed/rss2/ar.xml', 'name': 'Al Arabiya', 'weight': 0.9, 'language': 'ar'},
    'almonitor':{'url': 'https://www.al-monitor.com/rss', 'name': 'Al-Monitor', 'weight': 0.95, 'language': 'en'},
}
GDELT_QUERIES_EN = [
    '"Saudi Arabia" AND ("MBS" OR "crown prince" OR "royal court")',
    '"Saudi" AND ("Houthi" OR "missile" OR "drone" OR "air defense")',
    '"Aramco" OR "Abqaiq" OR "East-West pipeline"',
    '"Saudi" AND ("Israel" OR "normalization" OR "Iran talks")',
]
GDELT_QUERIES_ES = [
    'السعودية',
    'أرامكو',
]

# ============================================
# CACHE / REDIS HELPERS
# ============================================
CACHE_FILE = '/tmp/saudi_rhetoric_cache.json'
_background_scan_running = False
_background_scan_lock = threading.Lock()
_last_scan_started_at = None


def _redis_get(key):
    """Read a JSON value from Upstash Redis. Returns None if unavailable / missing."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=8
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        raw = body.get('result')
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        print(f"[KSA Rhetoric] Redis GET error ({key}): {str(e)[:120]}")
        return None


def _redis_set(key, value, ttl_hours=CACHE_TTL_HOURS):
    """Write a JSON value to Upstash Redis with TTL. Returns True on success."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        ttl_seconds = int(ttl_hours * 3600)
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{ttl_seconds}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[KSA Rhetoric] Redis SET error ({key}): {str(e)[:120]}")
        return False


def load_cache():
    """Try Redis first, fallback to /tmp file."""
    cached = _redis_get(REDIS_KEY_LATEST)
    if cached:
        return cached
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _redis_lpush_trim(key, value, max_len=336):
    """LPUSH + LTRIM to keep rolling history (336 = 14 days × 24 hourly entries).
    Canonical helper added May 22 2026 — mirrors Cuba pattern, read by wha_regional_bluf.prose_v2.
    Uses same direct-key style as _redis_set (Upstash accepts colons in keys without encoding)."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        # LPUSH the new entry
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/lpush/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8,
        )
        if resp.status_code != 200:
            return False
        # LTRIM to bound buffer length
        requests.post(
            f"{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_len - 1}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=8,
        )
        return True
    except Exception as e:
        print(f"[KSA Rhetoric] Redis LPUSH error ({key}): {str(e)[:120]}")
        return False


def save_cache(data):
    """Save to Redis + /tmp fallback."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if _redis_set(REDIS_KEY_LATEST, data, ttl_hours=CACHE_TTL_HOURS):
        print("[KSA Rhetoric] ✅ Saved to Redis")
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"[KSA Rhetoric] /tmp save error: {e}")


def is_cache_fresh(data):
    """Check if cache is younger than CACHE_TTL_HOURS."""
    if not data or 'cached_at' not in data:
        return False
    try:
        cached_at = datetime.fromisoformat(data['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        return age.total_seconds() < (CACHE_TTL_HOURS * 3600)
    except Exception:
        return False


# ============================================
# DATA FETCHERS — RSS / GDELT / NewsAPI / Brave
# ============================================
# Oct 18 2026: RSS RECENCY GATE. Google News search feeds (Urdu especially)
# return items a year old; with no date filter, Sep 2025 coverage of the pact
# SIGNING read as Pakistan "responding" in Oct 2026. Items whose date parses
# and is older than this are dropped. Undated items are KEPT -- a missing date
# is not evidence of an old one.
RSS_MAX_AGE_DAYS = 8


def _rss_entry_too_old(entry):
    st = entry.get('published_parsed') or entry.get('updated_parsed')
    if not st:
        return False
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc)
    except Exception:
        return False
    return (datetime.now(timezone.utc) - dt) > timedelta(days=RSS_MAX_AGE_DAYS)


def fetch_rss_articles(feed_id, feed_config, max_articles=30):
    """Fetch + parse a single RSS feed."""
    if not FEEDPARSER_AVAILABLE:
        return []
    articles = []
    try:
        feed = feedparser.parse(feed_config['url'])
        for entry in feed.entries[:max_articles]:
            if _rss_entry_too_old(entry):
                continue
            articles.append({
                'title':       entry.get('title', ''),
                'description': entry.get('summary', '') or entry.get('description', ''),
                'url':         entry.get('link', ''),
                'published':   entry.get('published', ''),
                'source':      feed_config['name'],
                'feed_id':     feed_id,
                'feed_type':   'rss',
                'language':    feed_config.get('language', 'en'),
                'feed_weight': feed_config.get('weight', 1.0),
            })
    except Exception as e:
        print(f"[KSA Rhetoric] RSS fetch error ({feed_id}): {str(e)[:120]}")
    return articles


def fetch_saudi_telegram(hours_back=48):
    """Pull the Yemen and Iran channel sets and shape them like articles.

    WHY THESE TWO SETS. The Houthi claim channels (al-Masirah, Ansar Allah
    media, SABA) live in YEMEN_CHANNELS; the IRGC/state and proxy-direction
    channels live in IRAN_CHANNELS. Those are the two voices that speak
    before and after a strike on Saudi Arabia. The Saudi country gate then
    throws away everything in them that is not about Saudi Arabia, which is
    most of it -- that is the gate doing its job, not a thin fetch.

    Never raises. Returns [] when Telegram is unavailable or floods.
    """
    if not TELEGRAM_AVAILABLE:
        return []
    out = []
    for label, fn in (('yemen', fetch_telegram_signals_yemen),
                      ('iran', fetch_telegram_signals_iran)):
        try:
            msgs = fn(hours_back=hours_back) or []
        except Exception as e:
            print(f"[KSA Rhetoric] Telegram {label} fetch error: {str(e)[:110]}")
            continue
        for m in msgs:
            tier = m.get('source_tier') or 'unverified'
            out.append({
                'title':       (m.get('title') or '')[:400],
                'description': (m.get('body') or m.get('title') or '')[:1200],
                'url':         m.get('url', ''),
                'published':   m.get('published', ''),
                'source':      m.get('source', 'Telegram'),
                'feed_id':     'telegram_' + label,
                'feed_type':   'telegram',
                'language':    (m.get('source_lang') or ['en'])[0],
                # Weight by TIER, not by a flat guess. unverified -> 0.0.
                'feed_weight': TELEGRAM_TIER_WEIGHT.get(tier, 0.0),
                # Provenance survives into scoring, tripwires and the page.
                'source_tier': tier,
                'source_lang': m.get('source_lang') or [],
                'channel':     m.get('channel', ''),
                'views':       m.get('views', 0) or 0,
            })
    if out:
        tiers = {}
        for a in out:
            tiers[a['source_tier']] = tiers.get(a['source_tier'], 0) + 1
        print(f"[KSA Rhetoric] Telegram: {len(out)} messages -- tiers: {tiers}")
    return out


def _check_tripwires_tiered(articles_for_actor):
    """Tripwires WITH a confirmation class.

    A tripwire asserts that an EVENT happened. When every article that fired
    it came from a channel aligned with the party making the claim, that is
    a claim being made -- not a confirmed event. It is surfaced either way
    and labelled, because suppressing it would hide a real pattern and
    reporting it as fact would manufacture one.

    Returns [{'id', 'severity', 'confirmation', 'claim_channels'}].
    """
    hits = {}
    for art in articles_for_actor or []:
        text = f"{art.get('title','')} {art.get('description','')}"
        tier = art.get('source_tier')          # None for RSS/GDELT/wire
        for tw_id, sev in _check_tripwires(text):
            rec = hits.setdefault(tw_id, {'id': tw_id, 'severity': sev,
                                          'confirmed_by': 0, 'claim_by': 0,
                                          'claim_channels': [], 'evidence': []})
            # v2.1.3: keep the articles that ACTUALLY fired the tripwire. The
            # page used to cite the actor's top article instead -- live 18 Oct
            # 'Infrastructure Strike' cited "Fijian conjoined twins successfully
            # separated". Evidence must be the evidence.
            if len(rec['evidence']) < 3:
                rec['evidence'].append({'title': art.get('title', ''), 'url': art.get('url', ''),
                                        'source': art.get('source', ''),
                                        'source_tier': tier})
            if tier is None or tier not in CLAIM_ONLY_TIERS:
                # No tier = conventional feed (RSS/GDELT/NewsAPI/Brave), which
                # is an independent source for this purpose.
                rec['confirmed_by'] += 1
            else:
                rec['claim_by'] += 1
                ch = art.get('channel')
                if ch and ch not in rec['claim_channels']:
                    rec['claim_channels'].append(ch)
    out = []
    for rec in hits.values():
        rec['confirmation'] = ('confirmed' if rec['confirmed_by'] > 0
                               else 'claim_sourced')
        rec['claim_channels'] = rec['claim_channels'][:4]
        out.append(rec)
    return out


# v2.1.0 Oct 18 2026: key bumped to :v2. The v1 baseline was built from an
# UNGATED count -- every claim-tier message on every axis channel (1,938 of
# 2,687 live), i.e. the whole axis media ecosystem, not Saudi. Reusing it
# would compare the first gated reading (tens) against ~1,955 and print a
# false SILENT. A fresh key restarts the baseline honestly at 'unread'.
CLAIM_BASELINE_KEY = 'rhetoric:saudi_arabia:claim_baseline:v2'


def build_claim_posture(all_articles, kinetic_level):
    """Claim-channel volume as its own reading, against a rolling baseline.

    WHY SEPARATE FROM THE ACTOR SCORE. Folding aligned-channel volume into
    houthi_yemen's score makes two different facts one number. The Houthis
    claiming loudly and the Houthis going quiet are BOTH signals, and the
    second is only visible if claim volume is counted apart.

    THE TELL. A channel that normally claims, falling silent while kinetic
    tempo holds, reads as tempo change rather than calm -- the same logic as
    the Africa trackers' claiming-actor silence anomaly. Reconstitution and
    operational-security posture both look like this.

    ABSENCE-HONEST. No baseline = 'unread', never 'quiet'. A FloodWait or an
    absent module is a COVERAGE GAP and says so; it must never render as
    claim-channel silence.
    """
    tg = [a for a in (all_articles or []) if a.get('feed_type') == 'telegram']
    # v2.1.0: GATED. A Houthi channel claiming a strike on Eilat or a US
    # destroyer is a claim -- but not a claim about Saudi Arabia. Only
    # claim-tier messages that pass the Saudi country gate count here.
    claim_all = [a for a in tg if a.get('source_tier') in CLAIM_ONLY_TIERS]
    claim = [a for a in claim_all
             if _passes_country_gate((a.get('title') or '') + ' ' + (a.get('description') or ''))]
    today = len(claim)

    if not TELEGRAM_AVAILABLE:
        return {'state': 'unread', 'reason': 'telegram_module_absent',
                'claim_volume': 0, 'baseline': None, 'channels': [],
                'telegram_total': 0, 'scope': 'saudi_gated',
                'note': ('Telegram is not deployed on this backend, so claim-channel '
                         'posture is UNREAD this cycle -- a coverage gap, not quiet.')}
    if not tg:
        return {'state': 'unread', 'reason': 'no_telegram_messages',
                'claim_volume': 0, 'baseline': None, 'channels': [],
                'telegram_total': 0, 'scope': 'saudi_gated',
                'note': ('No Telegram messages returned this scan (FloodWait, session '
                         'or connectivity). Claim posture is UNREAD -- a coverage gap, '
                         'not silence from the channels.')}

    hist = _redis_get(CLAIM_BASELINE_KEY) or []
    if not isinstance(hist, list):
        hist = []
    baseline = round(sum(hist) / len(hist), 1) if hist else None
    channels = sorted({a.get('channel') for a in claim if a.get('channel')})

    state, note = 'nominal', ''
    if baseline is None:
        state = 'unread'
        note = ('First cycles -- no claim-volume baseline yet. %d claim-channel '
                'messages logged; the silence read needs history before it means '
                'anything.' % today)
    elif baseline >= 3 and today == 0:
        state = 'silent'
        note = ('Claim channels are SILENT this cycle against a baseline of %.1f. '
                'For actors that normally claim, quiet reads as tempo change, not '
                'absence of activity -- historically consistent with reconstitution '
                'or operational-security posture ahead of renewed claiming.' % baseline)
    elif baseline >= 3 and today < baseline * 0.4:
        state = 'quieting'
        note = ('Claim-channel volume at %d against a baseline of %.1f -- a marked '
                'drop.' % (today, baseline))
    elif baseline and today > baseline * 2.0:
        state = 'surging'
        note = ('Claim-channel volume at %d against a baseline of %.1f. A claim surge '
                'is evidence that claims are being MADE, which is not evidence that '
                'the ground moved.' % (today, baseline))
    else:
        note = ('Claim-channel volume at %d against a baseline of %.1f -- within '
                'normal range.' % (today, baseline))

    if state in ('silent', 'quieting') and kinetic_level in ('high', 'surge'):
        note += (' Kinetic tempo is %s in the same window; claims dropping while '
                 'kinetics hold is the specific pattern, not the volume alone.'
                 % str(kinetic_level).upper())

    try:
        _redis_set(CLAIM_BASELINE_KEY, ([today] + hist)[:14], ttl_hours=24 * 30)
    except Exception:
        pass

    return {'state': state, 'reason': '', 'claim_volume': today,
            'baseline': baseline, 'channels': channels[:8],
            'telegram_total': len(tg),
            'claim_tier_total': len(claim_all),   # ungated, for context only
            'scope': 'saudi_gated',
            'note': note}


def fetch_all_rss():
    all_articles = []
    for feed_id, feed_config in RSS_FEEDS.items():
        articles = fetch_rss_articles(feed_id, feed_config)
        if articles:
            print(f"[KSA Rhetoric] RSS {feed_id}: {len(articles)} articles")
        all_articles.extend(articles)
    return all_articles


# Oct 18 2026 -- ROUTED THROUGH gdelt_gateway. This was one of 13 direct ME
# callers: no shared pacing, 0.5s between queries, and `if 429: return []` --
# a rate limit read as "no news". English keeps its explicit English-only
# filter (unchanged behaviour); other languages are mapped by the gateway to
# the names GDELT documents ('ara' -> sourcelang:arabic).
_GDELT_HEALTH = {'queries': 0, 'sensed': 0, 'cached': 0, 'articles': 0, 'not_sensed': {}}


def _gdelt_gw_query(query, language):
    return f'{query} sourcelang:english' if language == 'eng' else query


def fetch_gdelt_query(query, language='eng', days=7, max_articles=50):
    """One GDELT query through the shared gateway (absence-honest tally)."""
    if not _GDELT_GATEWAY:
        return []
    _GDELT_HEALTH['queries'] += 1
    try:
        raw, probe = _gw_fetch_probed(_gdelt_gw_query(query, language), language=language,
                                      timespan=f'{days}d', maxrecords=max_articles,
                                      label='saudi/' + language)
    except Exception as e:
        _GDELT_HEALTH['not_sensed']['exception'] = _GDELT_HEALTH['not_sensed'].get('exception', 0) + 1
        print(f"[KSA Rhetoric] GDELT gateway error: {str(e)[:100]}")
        return []
    if probe.get('sensed'):
        _GDELT_HEALTH['sensed'] += 1
        if probe.get('cached'):
            _GDELT_HEALTH['cached'] += 1
    else:
        r = probe.get('reason') or 'unknown'
        _GDELT_HEALTH['not_sensed'][r] = _GDELT_HEALTH['not_sensed'].get(r, 0) + 1
    articles = []
    for item in raw or []:
        articles.append({
            'title':       item.get('title', ''),
            'description': '',
            'url':         item.get('url', ''),
            'published':   item.get('published', ''),
            'source':      item.get('source') or 'GDELT',
            'feed_id':     'gdelt',
            'feed_type':   'gdelt',
            'language':    'ar' if language == 'ara' else 'en',
            'feed_weight': 0.85,
        })
    _GDELT_HEALTH['articles'] += len(articles)
    return articles


def fetch_all_gdelt(days=7):
    # Oct 18 2026: queries are REGISTERED with the trickle, which re-fetches them
    # slowly in the background into the shared cache; this scan then mostly
    # READS. The 0.5s sleeps are gone -- the gateway owns pacing.
    for k in list(_GDELT_HEALTH):
        _GDELT_HEALTH[k] = {} if k == 'not_sensed' else 0
    plan = [(q, 'eng') for q in GDELT_QUERIES_EN] + [(q, 'ara') for q in GDELT_QUERIES_ES]
    if _trickle_register and _GDELT_GATEWAY:
        try:
            _trickle_register('saudi', [{'query': _gdelt_gw_query(q, l), 'language': l,
                                      'timespan': f'{days}d', 'maxrecords': 50} for q, l in plan])
        except Exception as e:
            print(f"[KSA Rhetoric] trickle registration failed (non-fatal): {str(e)[:80]}")
    all_articles = []
    for q, lang in plan:
        all_articles.extend(fetch_gdelt_query(q, language=lang, days=days))
    h = _GDELT_HEALTH
    print(f"[KSA Rhetoric] GDELT: {len(all_articles)} articles (sensed {h['sensed']}/{h['queries']} "
          f"queries, {h['cached']} from cache" + (f"; NOT sensed: {h['not_sensed']}" if h['not_sensed'] else '') + ")")
    return all_articles


def fetch_newsapi(query, days=7):
    """Fetch from NewsAPI."""
    if not NEWSAPI_KEY:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    params = {
        'q':        query,
        'from':     from_date,
        'language': 'en',
        'sortBy':   'publishedAt',
        'pageSize': 30,
        'apiKey':   NEWSAPI_KEY,
    }
    try:
        resp = requests.get(NEWSAPI_BASE_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('articles', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': item.get('description', ''),
                'url':         item.get('url', ''),
                'published':   item.get('publishedAt', ''),
                'source':      (item.get('source') or {}).get('name', 'NewsAPI'),
                'feed_id':     'newsapi',
                'feed_type':   'newsapi',
                'language':    'en',
                'feed_weight': 0.9,
            })
        return articles
    except Exception:
        return []


def fetch_all_newsapi(days=7):
    queries = [
        'Saudi Arabia MBS crown prince',
        'Houthi attack Saudi OR missile OR drone',
        'Aramco Abqaiq pipeline OR facility',
        'Saudi Israel normalization',
        'Saudi Iran talks OR detente',
        'OPEC Saudi production cut',
        'Vision 2030 NEOM Saudi',
    ]
    all_articles = []
    for q in queries:
        all_articles.extend(fetch_newsapi(q, days=days))
        time.sleep(0.5)
    if all_articles:
        print(f"[KSA Rhetoric] NewsAPI: {len(all_articles)} articles")
    return all_articles


def fetch_brave(query, days=7):
    """Brave Search News API — tertiary fallback."""
    if not BRAVE_API_KEY:
        return []
    params = {'q': query, 'count': 20, 'spellcheck': '0'}
    try:
        resp = requests.get(
            BRAVE_BASE_URL,
            params=params,
            headers={
                'Accept':                'application/json',
                'Accept-Encoding':       'gzip',
                'X-Subscription-Token':  BRAVE_API_KEY,
            },
            timeout=10
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('results', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': item.get('description', ''),
                'url':         item.get('url', ''),
                'published':   item.get('age', ''),
                'source':      (item.get('source') or '') or 'Brave',
                'feed_id':     'brave',
                'feed_type':   'brave',
                'language':    'en',
                'feed_weight': 0.75,
            })
        return articles
    except Exception:
        return []


def fetch_all_brave(days=7, gdelt_count=0, newsapi_count=0):
    """Brave fallback — only fires when GDELT + NewsAPI returned <10 articles total."""
    if gdelt_count + newsapi_count >= 10:
        return []
    queries = [
        'Saudi Arabia 2026',
        'Houthi Saudi attack',
        'Aramco infrastructure',
        'Saudi Israel normalization',
    ]
    all_articles = []
    for q in queries:
        all_articles.extend(fetch_brave(q, days=days))
        time.sleep(0.5)
    if all_articles:
        print(f"[KSA Rhetoric] Brave fallback: {len(all_articles)} articles")
    return all_articles


# ============================================
# CLASSIFICATION + SCORING
# ============================================
def _normalize_text(text):
    """Lowercase + strip diacritics-light for keyword matching."""
    return (text or '').lower()


# ════════════════════════════════════════════════════════════
# COUNTRY GATE  (v2.0.0 Oct 11 2026)
#
# An article must name Saudi Arabia, a Saudi place, or a Saudi institution
# BEFORE any actor keyword is allowed to run. This is the Burkina pattern and
# it is load-bearing here for a specific reason: the matcher below was
# loosened from adjacent-substring to tokens-present, which is the only way
# it can see real headlines -- and loosening without a gate is how a tracker
# starts scoring Yemen-only and Iran-only stories as Saudi signals.
#
# Gate first, actors second. Always.
COUNTRY_GATE = (
    'saudi', 'saudi arabia', 'saudia', 'riyadh', 'jeddah', 'mecca', 'makkah',
    'medina', 'madinah', 'dhahran', 'dammam', 'abha', 'jizan', 'najran',
    'khamis mushait', 'tabuk', 'yanbu', 'jubail', 'ras tanura', 'abqaiq',
    'buqayq', 'khurais', 'neom', 'tadawul', 'aramco', 'kingdom of saudi',
    'ksa', 'king khalid international', 'king abdulaziz international',
    'al-ula', 'alula', 'qatif', 'eastern province',
    # v2.2.0: the monarch and crown prince by name. A succession headline can
    # name King Salman without ever saying "Saudi", and the gate rejected it
    # before the tripwire ran. Bare 'mbs' is deliberately NOT here: in
    # financial copy it means mortgage-backed securities.
    'king salman', 'bin salman', 'salman bin abdulaziz', 'allegiance council',
    '\u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629',      # AR  al-Sa'udiyya
    '\u0627\u0644\u0631\u064a\u0627\u0636',                     # AR  al-Riyadh
    '\u062c\u062f\u0629',                                          # AR  Jeddah
    '\u0623\u0631\u0627\u0645\u0643\u0648',                     # AR  Aramco
    # ── URDU (added 11 Oct 2026) ────────────────────────────────────
    # Without these the gate rejects every Urdu article BEFORE any actor
    # keyword runs, so Urdu keywords on mecca_pact_pakistan would have been
    # unreachable code. Urdu writes Saudi Arabia as 'سعودی عرب', which does
    # NOT contain the Arabic 'السعودية' -- different script conventions, same
    # country, and a substring test cannot bridge them. Caught before ship by
    # running real Urdu headlines through the gate.
    '\u0633\u0639\u0648\u062f\u06cc \u0639\u0631\u0628',       # UR  Saudi Arab
    '\u0633\u0639\u0648\u062f\u06cc',                            # UR  Saudi
    '\u0631\u06cc\u0627\u0636',                                    # UR  Riyadh
    '\u0645\u06a9\u06c1',                                           # UR  Makkah
)


def _passes_country_gate(text):
    """True when the text names Saudi Arabia or a Saudi place/institution."""
    t = _normalize_text(text)
    return any(g in t for g in COUNTRY_GATE)


def _kw_parts(k):
    """Split a keyword/pattern into match parts, the SAME way text is tokenized.

    v2.1.1 Oct 18 2026: keywords were split on spaces only, but text is split
    on every non-alphanumeric character. So 'east-west pipeline' needed the
    single token 'east-west', which the tokenizer can never produce -- the
    keyword was dead from 11 Oct. Same for 'saudi f-35', 'opec+ meeting',
    'iran-backed houthis', 'saudi two-state', and the 'east-west pipeline
    strike' TRIPWIRE (the Petroline is the Hormuz bypass). ASCII words are
    now split into their alphanumeric pieces; non-ASCII words stay whole.
    """
    out = []
    for w in k.split():
        if w.isascii():
            out.extend(re.findall(r"[a-z0-9]+", w))
        else:
            out.append(w)
    return out


def _kw_match(kw, text, tokens):
    """Does this keyword match?

    ── v2.0.0 Oct 11 2026: THE DEFECT THIS FIXES ─────────────────────────
    v1.0.0 did `kw.lower() in text` for every keyword. That is an ADJACENT
    SUBSTRING test, and multi-word keywords are written as word sequences:

        'houthi attack saudi' in "Houthi attack ON Saudi Arabia's airport"
            -> False.  One preposition and the match dies.

    9 of houthi_yemen's 11 keywords needed two or three words to be exactly
    adjacent. The only two that ever fired were the single-token Arabic ones,
    which is precisely why that card's sources were 100% GoogleNews-AR while
    the deadliest attack on Saudi soil of this war went unscored in English.
    Meanwhile aramco_energy's five SINGLE-token keywords over-collected, so
    the airport story surfaced on the oil card. Both halves, one root cause.

    Now: a single-token keyword matches on a word boundary; a multi-word
    keyword matches when ALL its tokens are present anywhere in the text.
    Order-free, because headlines reorder and insert prepositions freely.
    A keyword wrapped in "double quotes" keeps the old strict-phrase
    behaviour, for the handful where adjacency is the whole point.
    """
    k = kw.lower().strip()
    if len(k) > 2 and k[0] == '"' and k[-1] == '"':
        return k[1:-1] in text              # explicit strict phrase
    parts = _kw_parts(k)
    if not parts:
        return False
    if len(parts) == 1:
        k = parts[0]
        # Non-ASCII (Arabic) has no useful \b word boundary -- substring it.
        if not k.isascii():
            return k in text
        return k in tokens
    return all((p in tokens) if p.isascii() else (p in text) for p in parts)


def _classify_article_actor(article):
    """Match an article against actor keyword lists, COUNTRY-GATED.

    Returns (actor_id, hit_count) tuples for all matching actors. Multi-actor
    matching is allowed -- "Houthi strike on Riyadh airport, Aramco exports
    unaffected" legitimately hits both houthi_yemen and aramco_energy.
    """
    title = _normalize_text(article.get('title', ''))
    desc  = _normalize_text(article.get('description', ''))
    text  = title + ' ' + desc

    # GATE FIRST. An article that never names Saudi Arabia is not a Saudi
    # signal, however many actor keywords it happens to contain.
    if not _passes_country_gate(text):
        return []

    # v2.2.0: apostrophe dropped from the token class. "Riyadh's" was a single
    # token, so 'riyadh' never matched a possessive -- and headlines are full
    # of them (Saudi Arabia's, Riyadh's, Iran's). No keyword contains an
    # apostrophe, so nothing depended on it.
    tokens = set(re.findall(r"[a-z0-9]+", text))

    matches = []
    for actor_id, actor_data in ACTORS.items():
        hit_count = 0
        for kw in actor_data['keywords']:
            if _kw_match(kw, text, tokens):
                hit_count += 1
        if hit_count > 0:
            matches.append((actor_id, hit_count))
    return matches


# ════════════════════════════════════════════════════════════
# KEYWORDS SCORE. TRIPWIRES ASSERT.  (v2.2.0, 18 Oct 2026)
#
# On 11 Oct tripwires were moved onto the same tokens-present matcher as
# actor keywords, so they could see this war at all. That was right for
# keywords and WRONG for tripwires, and the live payload of 18 Oct proved it:
#
#   "NEW: Egypt's National Defense Council has approved providing 'all
#    necessary support' to help Saudi Arabia ... Egyptian C-130H military
#    transport aircraft already landed at King Fahd Air Base in Taif"
#
#   'new saudi king'  ->  new  (from the Telegram "NEW:" prefix)
#                         saudi (from "Saudi Arabia")
#                         king  (from "King Fahd Air Base")
#                     ->  succession_event, CONFIRMED, severity high,
#                         riding to the ME BLUF as a top signal.
#
# An Egyptian transport plane landing at an airbase was reported as a change
# of Saudi monarch, during a war. Saudi copy is wall-to-wall "King <facility>"
# (King Khalid Airport, King Fahd Air Base, King Abdulaziz Port) and Telegram
# prefixes breaking posts with "NEW:" -- so scattered-token matching on a
# succession pattern was a false positive waiting for a busy week.
#
# The asymmetry: a loose KEYWORD costs a fraction of an actor score. A loose
# TRIPWIRE broadcasts a false event. So tripwires get a precision-first rule:
# all tokens must appear inside ONE SENTENCE. An event assertion is a
# sentence; tokens scattered across a whole Telegram post are not one.
#
# Plural-tolerant ('missile' matches 'missiles') but NEVER prefix-matched:
# 'king' must not match 'kingdom', which appears in nearly every Saudi story.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?\u061f\u06d4])\s+|\n+|\s+[\u2014\u2013]\s+|[:;\u061b]\s+')


def _tripwire_match(pattern, text):
    """Sentence-scoped, plural-tolerant, quoted = strict phrase."""
    p = pattern.lower().strip()
    if len(p) > 2 and p[0] == '"' and p[-1] == '"':
        return p[1:-1] in text                      # explicit strict phrase
    parts = _kw_parts(p)                            # v2.1.1: hyphen-safe
    if not parts:
        return False
    for sent in _SENTENCE_SPLIT.split(text):
        if not sent:
            continue
        toks = set(re.findall(r"[a-z0-9]+", sent))
        ok = True
        for w in parts:
            if not w.isascii():
                if w not in sent:
                    ok = False; break
            elif not (w in toks or (w + 's') in toks or (w + 'es') in toks):
                ok = False; break
        if ok:
            return True
    return False


def _check_tripwires(text):
    """Check article text against TRIPWIRES patterns, COUNTRY-GATED.

    v2.0.0: patterns go through _kw_match, exactly like actor keywords. They
    had the identical adjacent-substring defect -- 'houthi missile riyadh'
    could not match "Houthi missiles struck Riyadh" -- so the tripwires were
    as blind to this war as the keywords were, and for the same reason.
    Fixing one without the other would have left the loudest events unseen.

    The country gate applies here too: tokens-present matching without it
    would fire Saudi tripwires on Yemen-only copy.
    """
    text_lower = _normalize_text(text)
    if not _passes_country_gate(text_lower):
        return []
    triggered = []
    for tw_id, tw_data in TRIPWIRES.items():
        for pattern in tw_data['patterns']:
            # v2.2.0: sentence-scoped, NOT the actor-keyword matcher.
            if _tripwire_match(pattern, text_lower):
                triggered.append((tw_id, tw_data['severity']))
                break  # only count each tripwire once per article
    return triggered


def _score_actor_articles(articles_for_actor, actor_id):
    """
    Compute weighted score for an actor: sum of (feed_weight × keyword-density × recency).
    Returns dict with score, article_count, language_breakdown, sources, top_articles, tripwires.
    """
    if not articles_for_actor:
        return {
            'score': 0,
            'article_count': 0,
            'language_breakdown': {},
            'sources': [],
            'top_articles': [],
            'tripwires': [],
            'tier_breakdown': {},
            'telegram_count': 0,
            'claim_tier_count': 0,
        }

    score = 0
    lang_count = {}
    src_count = {}
    tripwires_seen = set()
    tier_counts = {}
    tg_count = 0
    claim_count = 0

    for art in articles_for_actor:
        _tier = art.get('source_tier')
        if _tier:
            tier_counts[_tier] = tier_counts.get(_tier, 0) + 1
            if art.get('feed_type') == 'telegram':
                tg_count += 1
            if _tier in CLAIM_ONLY_TIERS:
                claim_count += 1
        feed_w = art.get('feed_weight', 1.0)
        kw_hits = art.get('_actor_hits', 1)  # set by classifier
        kw_factor = min(1.0 + (kw_hits - 1) * 0.15, 2.0)  # diminishing returns
        article_score = feed_w * kw_factor
        score += article_score

        lang = art.get('language', 'en')
        lang_count[lang] = lang_count.get(lang, 0) + 1
        src = art.get('source', 'Unknown')
        src_count[src] = src_count.get(src, 0) + 1

        # Tripwire check
        full_text = f"{art.get('title', '')} {art.get('description', '')}"
        for tw_id, severity in _check_tripwires(full_text):
            tripwires_seen.add((tw_id, severity))

    # Sort articles by article_score descending
    sorted_articles = sorted(
        articles_for_actor,
        key=lambda a: a.get('feed_weight', 1.0) * min(1.0 + (a.get('_actor_hits', 1) - 1) * 0.15, 2.0),
        reverse=True,
    )
    top_articles = []
    for a in sorted_articles[:8]:
        top_articles.append({
            'title':       a.get('title', ''),
            'url':         a.get('url', ''),
            'source':      a.get('source', ''),
            'language':    a.get('language', 'en'),
            'published':   a.get('published', ''),
            'feed_type':   a.get('feed_type', ''),
            # v2.1.0: the page must be able to show that a source is an
            # aligned claim channel rather than a wire. Same headline, very
            # different evidentiary weight.
            'source_tier': a.get('source_tier'),
            'channel':     a.get('channel'),
        })

    sources = sorted(src_count.items(), key=lambda x: -x[1])[:6]

    return {
        'score':              round(score, 2),
        'article_count':      len(articles_for_actor),
        'language_breakdown': lang_count,
        'sources':            [{'source': s, 'count': c} for s, c in sources],
        'top_articles':       top_articles,
        # v2.1.0: tripwires now carry a CONFIRMATION CLASS. A tripwire fired
        # only by channels aligned with the claiming party is a claim, and is
        # labelled rather than suppressed -- the Sahel lesson applied to
        # Telegram.
        'tripwires':          _check_tripwires_tiered(articles_for_actor),
        # Provenance mix for this actor, so a reader can see whether a score
        # is carried by wires or by claim channels. Those are different
        # readings and must not render identically.
        'tier_breakdown':     tier_counts,
        'telegram_count':     tg_count,
        'claim_tier_count':   claim_count,
    }


# ============================================
# CROSS-TRACKER FINGERPRINT INTEGRATION
# ============================================
def _read_commodity_pressure_for_saudi_arabia():
    """
    Read commodity supply-risk fingerprints for Saudi Arabia's exposed commodities
    via the WHA-local commodity proxy (commodity_proxy_wha.py).

    The proxy caches ME-backend fingerprints in WHA Redis with 1-hour TTL,
    so this call is a cheap localhost hit on the proxy — no cross-backend
    HTTP latency unless the WHA-local cache misses.

    Returns dict {commodity_id: risk_dict} for any active pressure.
    Returns {} on error / empty / proxy unavailable — graceful degradation.
    """
    try:
        url = f"{ME_BACKEND_SELF_URL}/api/commodity-pressure/saudi_arabia"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        # Proxy returns {fingerprints: {commodity_id: risk_dict}, ...}
        return data.get('fingerprints', {}) or {}
    except Exception as e:
        print(f"[KSA Rhetoric] commodity proxy read error: {str(e)[:120]}")
        return {}


def _read_commodity_pressure_story_for_saudi_arabia():
    """
    Read the composite pressure STORY from the WHA-local commodity proxy
    (/api/commodity-pressure/saudi_arabia -- 12hr-cached pass-through of the ME backend's
    /api/commodity-pressure/saudi_arabia). This is the SAME payload the Saudi Arabia stability
    page renders (composite points, alert band, per-commodity global alerts),
    so the rhetoric tracker and stability page tell ONE story.

    Returns compact dict or {} on any failure (graceful degradation):
      {alert, points, profile_count, commodities: {commodity_id: global_alert_level}}
    """
    try:
        url = f"{ME_BACKEND_SELF_URL}/api/commodity-pressure/saudi_arabia"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        commodities = {}
        for tile in (data.get('commodity_summaries') or []):
            cid = tile.get('commodity')
            if cid:
                commodities[cid] = tile.get('global_alert_level') or 'normal'
        return {
            'alert':         (data.get('alert_level') or 'normal').lower(),
            'points':        round(float(data.get('commodity_pressure') or 0), 1),
            'profile_count': data.get('profile_count') or len(commodities),
            'commodities':   commodities,
        }
    except Exception as e:
        print(f"[KSA Rhetoric] commodity story read error: {str(e)[:120]}")
        return {}


# Oct 18 2026 -- TWO CONVENTIONS, ONE READER. Iran writes its own key
# (crosstheater:iran:fingerprint). Israel and Yemen write a SLICE of the shared
# collective dict rhetoric:crosstheater:fingerprints (spoke_wheel_reader
# convention #3). This reader only looked at the first, so Israel and Yemen
# read as "not reporting" every scan while both trackers were running fine.
# Fix is in the READER (one writer, many readers): dedicated key first, then
# the collective slice. A slice older than CROSSTHEATER_FRESH_HOURS is reported
# as stale -- never presented as a current reading.
COLLECTIVE_CROSSTHEATER_KEY = 'rhetoric:crosstheater:fingerprints'
CROSSTHEATER_FRESH_HOURS = 24
_COLLECTIVE_SLICE = {'iran_fingerprint': 'iran', 'israel_fingerprint': 'israel',
                     'yemen_fingerprint': 'yemen', 'saudi_fingerprint': 'saudi_arabia'}


def _slice_age_hours(ts):
    try:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _read_one_fingerprint(label, redis_key, collective_cache):
    """Returns (payload or None, absence_reason or None)."""
    val = _redis_get(redis_key)
    if val:
        return val, None
    if 'd' not in collective_cache:
        collective_cache['d'] = _redis_get(COLLECTIVE_CROSSTHEATER_KEY) or {}
    coll = collective_cache['d'] if isinstance(collective_cache['d'], dict) else {}
    sl = coll.get(_COLLECTIVE_SLICE.get(label, label.replace('_fingerprint', '')))
    if not isinstance(sl, dict) or not sl:
        return None, label
    age = _slice_age_hours(sl.get('ts'))
    if age is not None and age > CROSSTHEATER_FRESH_HOURS:
        return None, '%s (stale %dh)' % (label, int(age))
    out = dict(sl)
    out['_source'] = 'collective'
    return out, None


def _read_crosstheater_amplifiers():
    """
    Sibling-tracker fingerprints that shape Saudi Arabia's analytical context
    (the wheels, read from the shared Redis -- absence-honest when missing):
      iran_fingerprint   -- crosstheater:iran:fingerprint   (patron of the Houthi front)
      israel_fingerprint -- crosstheater:israel:fingerprint (Accords axis / defense path)
      yemen_fingerprint  -- crosstheater:yemen:fingerprint  (the kinetic front itself)
    """
    amplifiers = {}
    candidate_keys = {
        'iran_fingerprint':   'crosstheater:iran:fingerprint',
        'israel_fingerprint': 'crosstheater:israel:fingerprint',
        'yemen_fingerprint':  'crosstheater:yemen:fingerprint',
    }
    absent = []
    _coll = {}
    for label, redis_key in candidate_keys.items():
        val, why = _read_one_fingerprint(label, redis_key, _coll)
        if val:
            amplifiers[label] = val
        else:
            absent.append(why)
    # v2.1.0: absence is REPORTED, not inferred. Live 18 Oct showed only
    # iran_fingerprint -- israel/yemen vanished with nothing saying so.
    # Module-level so the result dict can carry it without changing the
    # return shape every caller (and the interpreter) depends on.
    global _CROSSTHEATER_ABSENT
    _CROSSTHEATER_ABSENT = absent
    if absent:
        print(f"[KSA Rhetoric] crosstheater NOT REPORTING: {', '.join(absent)}")
    return amplifiers

_CROSSTHEATER_ABSENT = []

def _builtin_fallback_signals(composite_score, composite_level, vector_scores,
                              vector_levels, actor_summaries, tripwires_global,
                              disaster_state):
    """Interpreter-absent fallback (v1 ships without a dedicated interpreter):
    compact executive summary + canonical-ish top_signals so the page and the
    Asia BLUF always have something honest to render. Estimative voice only."""
    sigs = []
    # tripwire hits first
    for tw in (tripwires_global or [])[:3]:
        name = tw.get('tripwire', tw.get('id', 'tripwire')) if isinstance(tw, dict) else str(tw)
        sev  = tw.get('severity', 'high') if isinstance(tw, dict) else 'high'
        sigs.append({'level': sev, 'type': 'tripwire', 'priority': 10,
                     'category': 'tripwire', 'theatre': 'saudi_arabia',
                     'pressure_type': 'kinetic',
                     'short_text': f"\U0001f1f8\U0001f1e6 SAUDI ARABIA tripwire: {str(name).replace('_',' ')}",
                     'long_text':  f"SAUDI ARABIA tripwire fired: {str(name).replace('_',' ')} -- "
                                   f"pattern-level escalation event this scan window."})
    # friction+detente dual-signal read: iran_saudi elevated WITH detente vocabulary
    _iran = (actor_summaries or {}).get('iran_saudi', {})
    if _iran.get('level') in ('high', 'surge'):
        sigs.append({'level': _iran['level'], 'type': 'friction_spike', 'priority': 9,
                     'category': 'friction_spike', 'theatre': 'saudi_arabia',
                     'pressure_type': 'diplomatic',
                     'short_text': '\U0001f1f8\U0001f1e6 SAUDI ARABIA: Iran-file rhetoric at ' + _iran['level'].upper(),
                     'long_text':  'Iran-Saudi signal tempo at ' + _iran['level'] + ' -- on the friction-with-'
                                   'detente-shim tier, surges here read against the Beijing-2023 normalization '
                                   'baseline: friction spikes WITHOUT detente rupture have historically stayed '
                                   'contained; watch the detente_rupture tripwire as the brake-failure tell.'})
    # surge/high actors
    for akey, summ in (actor_summaries or {}).items():
        lvl = summ.get('level','low') if isinstance(summ,dict) else 'low'
        if lvl in ('high','surge'):
            sigs.append({'level': lvl, 'type': 'actor_signal', 'priority': 7,
                         'category': 'actor_signal', 'theatre': 'saudi_arabia',
                         'pressure_type': 'kinetic',
                         'short_text': f"\U0001f1f8\U0001f1e6 {akey.replace('_',' ').title()} at {lvl.upper()}",
                         'long_text':  f"SAUDI ARABIA actor {ACTORS.get(akey, {}).get('name', akey)} scanning at {lvl} -- "
                                       f"elevated statement tempo/severity versus baseline."})
    sigs.sort(key=lambda x: -x.get('priority',0))

    vecs_hot = [k.replace('_',' ') for k,v in (vector_levels or {}).items()
                if v in ('elevated','high','surge')]
    parts = [f"Saudi Arabia composite {composite_score:.1f} ({composite_level.upper()})."]
    parts.append(f"Active vectors: {', '.join(vecs_hot[:3])}." if vecs_hot
                 else "All four vectors at baseline this scan.")
    parts.append("Friction-tier node with detente shim: Iran friction vs Beijing-2023 "
                 "normalization track; Accords drift on the Israel axis -- convergence read, not prediction.")
        # --- Fallback So-What bullets (v1: interpreter-less; vector-level driven) ---
    so_what = []
    _esc = ('elevated', 'high', 'surge')
    _sw = {
        'kinetic_inbound': "Kinetic-inbound at {lvl}. What it means: strike-cycle tempo at this level has historically added a risk premium to Brent within the same week and repriced war-risk insurance on Gulf and Red Sea routings. Abqaiq 2019 is the anchor precedent -- one facility strike halved output in a day. Who feels it first: crude buyers, tanker insurers, Saudi air-defense procurement. Confirmation gauges: Brent tile on the stability page, intercept-announcement cadence, Abha/Jeddah airport advisories.",
        'energy_infrastructure': "Energy-infrastructure at {lvl}. What it means: facility/pipeline signal tempo transmits to Brent and refined-product cracks within days if sustained; the East-West Petroline to Yanbu is the bypass that caps the Hormuz-closure scenario at roughly 5M bpd. IMEC corridor signals ride this vector as the counter-BRI story. Who feels it: crude importers globally, then downstream fuel markets. Confirmation gauges: Brent + Aramco tiles, Petroline throughput reporting.",
        'normalization_watch': "Normalization-watch at {lvl}. What it means: signature-language cycles at this tempo have historically moved the whole regional realignment picture -- a Saudi-Israel deal would reprice defense pacts, Israeli market access, and the Palestinian file simultaneously; talks collapsing re-anchors the holdout position. Who feels it: every ME desk at once. Confirmation gauges: US-brokered package reporting, Palestinian-state precondition language.",
        'domestic_transformation': "Domestic-transformation at {lvl}. What it means: Vision 2030 re-scoping and decree tempo at this level reads as fiscal pressure -- PIF is a mega-allocator, so deployment shifts transmit into global asset markets (tech, sports, infrastructure) within quarters. Succession signals ride this vector at maximum weight. Who feels it: PIF portfolio sectors, expat labor markets, contractors. Confirmation gauges: giga-project milestone reporting, budget statements, the Tadawul tile.",
    }
    for _vec, _lvl in (vector_levels or {}).items():
        if _lvl in _esc and _vec in _sw:
            so_what.append({'weight': 0.9, 'bullet': _sw[_vec].format(lvl=str(_lvl).upper())})
    if not so_what:
        so_what.append({'weight': 0.3, 'bullet':
            "All four vectors at baseline this scan. Baseline for a friction-tier node still means the detente shim is load-bearing: Iran friction runs against the Beijing-2023 normalization track, and the Accords drift axis stays live. Quiet is a posture, not an absence."})
    so_what.sort(key=lambda b: -b['weight'])
    return sigs[:8], ' '.join(parts), so_what[:6]


def _mecca_pact_reading(actor_levels):
    """The Mecca Pact reading -- ONE writer for the fingerprint AND the page.

    v2.1.2 Oct 18 2026: the note used to be a constant ("the pact is paper"),
    so it asserted paper even when guarantors WERE responding. Now a state:
      responding      -- a guarantor at elevated+
      flat_under_fire -- Saudi kinetic tempo high/surge, no guarantor moving.
                         THE FINDING the falsifier names.
      no_test         -- no kinetic cycle to respond to; flat means nothing yet.
    """
    _O = ['low', 'normal', 'elevated', 'high', 'surge']
    tk = actor_levels.get('mecca_pact_turkiye', 'low')
    pk = actor_levels.get('mecca_pact_pakistan', 'low')
    eg = actor_levels.get('egypt_support', 'low')   # NON-pact: reported, never counted as a guarantor
    kin = max(actor_levels.get('houthi_yemen', 'low'),
              actor_levels.get('saudi_mod_airdefense', 'low'), key=_O.index)
    responding = [g for g, lv in (('turkiye', tk), ('pakistan', pk))
                  if lv in ('elevated', 'high', 'surge')]
    if responding:
        reading = 'responding'
        note = ('Guarantor tempo is moving (' + ', '.join(responding) + ') against a Saudi '
                'kinetic cycle at ' + kin + '. Words first: watch whether deployment, '
                'intercept or basing vocabulary follows.')
    elif kin in ('high', 'surge'):
        reading = 'flat_under_fire'
        note = ('Saudi kinetic tempo is at ' + kin + ' and neither guarantor is moving. '
                'This is a READING, not a missing sensor: flat guarantor tempo through '
                'a strike cycle is the pact-is-paper pattern.')
    else:
        reading = 'no_test'
        note = ('No Saudi strike cycle this scan, so guarantor quiet tests nothing yet.')
    third_party = [n for n, lv in (('egypt', eg),) if lv in ('elevated', 'high', 'surge')]
    if third_party and reading == 'flat_under_fire':
        note += (' Meanwhile a NON-signatory is moving (' + ', '.join(n.title() for n in third_party) + ' at ' + eg +
                 '): the outsider responding before the guarantors is itself the finding.')
    elif third_party:
        note += (' Non-pact support is also moving (' + ', '.join(n.title() for n in third_party) + ' at ' + eg + ').')
    return {'turkiye_level': tk, 'pakistan_level': pk, 'kinetic_level': kin,
            'guarantors_responding': ['mecca_pact_' + g for g in responding],
            'third_party': {'egypt': eg},
            'third_party_responding': third_party,
            'reading': reading, 'note': note}


def _write_saudi_fingerprints(actor_levels, vector_scores, tripwires_global):
    """
    Saudi crosstheater slice -- FRICTION-TIER node with DETENTE SHIM (Iran wheel).
    Slices (canonical hub-agnostic spoke schema, AZ lineage):
      iran   = friction+detente  (dual-polarity: the shim)
      china  = counter_bri       (IMEC hub -- reverse polarity on the China wheel)
      israel = normalization     (Accords drift axis: holdout <-> signature)
      us     = ally              (security-guarantee anchor)
    Consumers: ME BLUF, GPI Iran-wheel narrative, future US wheel.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    def _slice(actor_key, role):
        lvl = actor_levels.get(actor_key, 'low')
        return {'level': lvl, 'role': role,
                'active': lvl in ('elevated', 'high', 'surge')}

    hub_presence = {
        'iran':   _slice('iran_saudi', 'friction_detente'),
        'china':  {'level': 'normal', 'role': 'counter_bri', 'active': False,
                   'note': 'IMEC counter-hub -- level tracks via commodity/IMEC signals, not a rhetoric actor v1'},
        'israel': _slice('accords_normalization', 'normalization'),
        'us':     _slice('us_saudi', 'ally'),
        # NEW 11 Oct 2026 -- the Mecca Pact guarantor, and Turkiye is a HUB.
        'turkey': _slice('mecca_pact_turkiye', 'mecca_pact_guarantor'),
    }
    slices_active = sum(1 for w in hub_presence.values() if w.get('active'))

    _lvl_to_int = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
    _tk = actor_levels.get('mecca_pact_turkiye', 'low')

    slice_payload = {
        'ts':               now_iso,
        'theatre':          'saudi_arabia',
        'country':          'saudi_arabia',
        'node_class':       'friction_detente',
        'hub_presence':     hub_presence,
        'slices_active':    slices_active,
        'detente_intact':   not any((tw.get('id') == 'detente_rupture') for tw in (tripwires_global or []) if isinstance(tw, dict)),
        'kinetic_inbound':  vector_scores.get('kinetic_inbound', 0),
        'normalization_watch': vector_scores.get('normalization_watch', 0),
        'guarantor_response':  vector_scores.get('guarantor_response', 0),
        'houthi_level':     actor_levels.get('houthi_yemen', 'low'),
        # ── turkey_spoke (11 Oct 2026) ──────────────────────────────────
        # The block spoke_wheel_reader._extract_hub_detail() looks for when
        # the TURKEY wheel reads Saudi Arabia. rhetoric_tracker_turkey.py has
        # no Saudi actor and no mention of Mecca at all, so without this the
        # pact is invisible on both ends. Writing it HERE means the Turkey
        # wheel gains a Saudi spoke with no change to the Europe backend --
        # which is the whole promise of the shared reader.
        #
        # NO 'trajectory' KEY. Saudi has no directional sensor for Turkiye;
        # defaulting one to 'holding' would invent a reading from a module
        # that never ran. Absent means no sensor, and the panel says so.
        'turkey_spoke': {
            'level': _lvl_to_int.get(_tk, 0),
            'role': 'mecca_pact_guarantor',
            'note': ('Mecca Joint Defence Agreement (Aug 2026; collective '
                     'deterrence activated 5 Oct 2026). Turkiye is a guarantor '
                     'of Saudi Arabia, so Ankara reads here as an inbound '
                     'commitment rather than an outbound projection.'),
        },
        # Pakistan is the OTHER guarantor and is deliberately NOT written as a
        # spoke block: it is not in spoke_wheel_reader._KNOWN_HUBS, so nothing
        # would discover it, and inventing a Pakistan wheel to hold one actor
        # would be a hub asserted rather than measured. It rides as an actor
        # on the guarantor_response vector until a Pakistan tracker drives it.
        'mecca_pact': _mecca_pact_reading(actor_levels),
        'tripwires':        tripwires_global[:5] if isinstance(tripwires_global, list) else [],
    }
    _redis_set('crosstheater:saudi_arabia:fingerprint', slice_payload, ttl_hours=14)
    print(f"[KSA Rhetoric] Crosstheater slice written -- slices_active={slices_active}, "
          f"detente_intact={slice_payload['detente_intact']}")

def _compute_saudi_l5_gate(tripwires_global, actor_summaries, vector_scores):
    """
    Per platform L5 Reservation Contract: Saudi Arabia L5 "Active Crisis" requires
    an explicit kinetic / humanitarian / economic / diplomatic L5 trigger.

    Saudi Arabia is a contested-node tracker. L5 'Active Crisis' is reserved for
    crisis-class events: Abqaiq-class infrastructure destruction with sustained
    output loss, direct Iran-Saudi state-on-state war, royal-succession crisis
    with kinetic contest, or Hajj mass-casualty catastrophe. Scaffold today -- the
    weekend audit adds severity-5 tripwires per axis; until then the gate
    correctly returns any=False.

    Returns dict with axis flags + reason string.
    """
    gate = {
        'kinetic':      False,
        'humanitarian': False,
        'economic':     False,
        'diplomatic':   False,
        'reason':       '',
        'any':          False,
    }

    # Convert tripwires_global to a flat set for lookup by (actor_id, tw_id)
    fired_tws = set()
    for entry in tripwires_global or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            fired_tws.add(f"{entry[0]}:{entry[1]}")
        elif isinstance(entry, dict):
            actor = entry.get('actor_id', '')
            twid  = entry.get('tw_id', '')
            if actor and twid:
                fired_tws.add(f"{actor}:{twid}")

    reasons = []

    # ── KINETIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: direct Iran-Saudi state war, sustained missile campaign
    # on population centers, succession crisis with kinetic contest. No severity-5 tripwires
    # currently defined in Saudi Arabia's ACTORS dict. Awaits weekend audit.
    # Today: never fires.

    # ── HUMANITARIAN L5 (scaffold — refine in weekend audit) ──
    # Would fire on: famine-scale rupture, catastrophic quake displacement,
    # deportation-wave humanitarian collapse. No severity-5 tripwires currently defined.
    # Today: never fires.

    # ── ECONOMIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: riyal peg collapse, Aramco output halved beyond 30 days,
    # sovereign-wealth crisis. No severity-5 tripwires currently defined.
    # Today: never fires.

    # ── DIPLOMATIC L5 (scaffold — refine in weekend audit) ──
    # Would fire on: recognition-cascade rupture, wheel-power embassy
    # closures, UN-mandate collapse. No severity-5 tripwires currently defined.
    # Today: never fires.

    gate['any']    = any(gate[k] for k in ('kinetic', 'humanitarian', 'economic', 'diplomatic'))
    gate['reason'] = '; '.join(reasons) if reasons else 'No L5 axis trigger fired (L5 reserved for crisis-class events: sustained infrastructure destruction, Iran-Saudi state war, succession crisis)'

    return gate


def _build_saudi_signal_text(theatre_level, theatre_score, vector_levels, actor_summaries, l5_capped=False):
    """
    Build short_text + long_text for Saudi Arabia's theatre_high signal.
    Returns dict {'short': str, 'long': str}.
    """
    # Identify top vectors at elevated+
    vectors_active = []
    if isinstance(vector_levels, dict):
        for vec, lvl in vector_levels.items():
            if lvl in ('elevated', 'high', 'surge'):
                vectors_active.append(vec.replace('_', ' '))

    vectors_brief = ', '.join(vectors_active[:3]) if vectors_active else 'baseline'

    # Identify top actors at elevated+
    actors_active = []
    if isinstance(actor_summaries, dict):
        for actor, summary in actor_summaries.items():
            lvl = summary.get('level', 'low') if isinstance(summary, dict) else 'low'
            if lvl in ('elevated', 'high', 'surge'):
                actors_active.append(actor.replace('_', ' '))

    actors_brief = ', '.join(actors_active[:3]) if actors_active else ''

    label_map = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning',
                 3: 'Direct Threat', 4: 'Coercion', 5: 'Active Crisis'}
    label = label_map.get(theatre_level, 'Monitoring')

    short = f"🇸🇦 SAUDI ARABIA L{theatre_level} {label} — {vectors_brief}"
    if len(short) > 120:
        short = short[:117] + '...'

    long_parts = [f"🇸🇦 SAUDI ARABIA at L{theatre_level} {label} (theatre score {theatre_score}/100)."]
    if vectors_active:
        long_parts.append(f"Active vectors: {vectors_brief}.")
    if actors_active:
        long_parts.append(f"Top actors: {actors_brief}.")
    if l5_capped:
        long_parts.append("L5 axis gate did not fire — capped at L4 ceiling per platform L5 Reservation Contract.")
    else:
        # v2.1.0: was "four mixed-polarity wheels (Iran friction, Pakistan
        # kinetic, ...)" -- written before the Mecca Pact. Pakistan is a treaty
        # guarantor now; calling it a kinetic wheel inverted the alliance.
        long_parts.append("Saudi Arabia is the Mecca Pact anchor (with Turkiye and Pakistan as guarantors) and a friction-tier node on the Iran wheel: Houthi kinetic front inbound, Accords holdout anchored by the Palestinian file.")

    return {'short': short, 'long': ' '.join(long_parts)}


# ============================================
# MAIN SCAN ORCHESTRATOR
# ============================================
def scan_saudi_rhetoric(force=False, days=7):
    """
    Full scan: fetch from all sources, classify per actor, score, build summaries,
    write fingerprints, return result.
    """
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    scan_start = time.time()

    print(f"[KSA Rhetoric] === Scan start (force={force}, days={days}) ===")

    # ── Fetch all sources ──
    rss_articles = fetch_all_rss()
    print(f"[KSA Rhetoric] RSS total: {len(rss_articles)}")
    gdelt_articles = fetch_all_gdelt(days=days)
    newsapi_articles = fetch_all_newsapi(days=days)
    brave_articles = fetch_all_brave(
        days=days,
        gdelt_count=len(gdelt_articles),
        newsapi_count=len(newsapi_articles),
    )

    telegram_articles = fetch_saudi_telegram(hours_back=max(24, days * 24))
    all_articles = (rss_articles + gdelt_articles + newsapi_articles
                    + brave_articles + telegram_articles)
    # Dedupe by URL
    seen_urls = set()
    deduped = []
    for a in all_articles:
        u = a.get('url', '')
        if u and u not in seen_urls:
            seen_urls.add(u)
            deduped.append(a)
    all_articles = deduped
    print(f"[KSA Rhetoric] Articles after dedup: {len(all_articles)}")

    # ── Classify articles by actor ──
    articles_by_actor = {actor_id: [] for actor_id in ACTORS.keys()}
    for art in all_articles:
        matches = _classify_article_actor(art)
        for actor_id, hit_count in matches:
            art_copy = dict(art)
            art_copy['_actor_hits'] = hit_count
            articles_by_actor[actor_id].append(art_copy)

    # ── Score each actor ──
    actor_summaries = {}
    actor_levels = {}
    tripwires_global = []
    for actor_id, actor_data in ACTORS.items():
        scored = _score_actor_articles(articles_by_actor[actor_id], actor_id)
        baseline = actor_data['baseline_statements_per_week']
        level = actor_alert_level(scored['score'], baseline)
        actor_levels[actor_id] = level

        actor_summaries[actor_id] = {
            'name':         actor_data['name'],
            'flag':         actor_data['flag'],
            'icon':         actor_data['icon'],
            'color':        actor_data['color'],
            'role':         actor_data['role'],
            'description':  actor_data['description'],
            'vector':       actor_data['vector'],
            'score':        scored['score'],
            'level':        level,
            'baseline':     baseline,
            'article_count':       scored['article_count'],
            'language_breakdown':  scored['language_breakdown'],
            'sources':             scored['sources'],
            'top_articles':        scored['top_articles'],
            'tripwires':           scored['tripwires'],
        }
        for tw in scored['tripwires']:
            # tw now carries confirmation / claim_channels; both ride up so the
            # interpreter and the page can label a claim-sourced tripwire.
            tripwires_global.append({'actor': actor_id, **tw})

    # ── Compute 4-vector composite scores ──
    vector_scores = {}
    vector_levels = {}
    for vector_id, member_actors in VECTOR_GROUPS.items():
        total = sum(actor_summaries[a]['score'] for a in member_actors if a in actor_summaries)
        vector_scores[vector_id] = round(total, 2)
        # Level for vector = max actor level in vector
        levels_seen = [actor_summaries[a]['level'] for a in member_actors if a in actor_summaries]
        order = ['low', 'normal', 'elevated', 'high', 'surge']
        if levels_seen:
            vector_levels[vector_id] = max(levels_seen, key=lambda lv: order.index(lv))
        else:
            vector_levels[vector_id] = 'low'

    # ── Read cross-tracker context ──
    commodity_pressure = _read_commodity_pressure_for_saudi_arabia()
    # Attach the composite pressure story under a reserved key -- consumers
    # iterating per-commodity fingerprints skip underscore-prefixed keys.
    _story = _read_commodity_pressure_story_for_saudi_arabia()
    if _story:
        commodity_pressure['_pressure_story'] = _story
    crosstheater_amplifiers = _read_crosstheater_amplifiers()

    # ── Claim-channel posture (v2.1.0) ──
    # Counted APART from the actor scores on purpose: claiming loudly and
    # going quiet are both signals, and the second is only visible if claim
    # volume has its own number.
    claim_posture = build_claim_posture(
        all_articles, vector_levels.get('kinetic_inbound', 'low'))
    print(f"[KSA Rhetoric] Claim posture: {claim_posture['state']} "
          f"(vol={claim_posture['claim_volume']}, baseline={claim_posture['baseline']})")

    # ── Write Saudi Arabia fingerprints for downstream consumers ──
    _write_saudi_fingerprints(actor_levels, vector_scores, tripwires_global)

    # ── Compute composite Saudi Arabia pressure score ──
    composite_score = round(sum(vector_scores.values()), 2)

    # (No disaster-sensor cross-read: GCC trackers are market/energy-sensored by design.)
    disaster_state = {}
    composite_level = max(
        (actor_summaries[a]['level'] for a in actor_summaries),
        key=lambda lv: ['low', 'normal', 'elevated', 'high', 'surge'].index(lv),
        default='low',
    )

    # ── Build executive summary + so-what + top signals via interpreter ──
    if KSA_INTERPRETER_AVAILABLE:
        try:
            top_signals = build_top_signals(actor_summaries, tripwires_global,
                                             commodity_pressure, crosstheater_amplifiers)
            executive_summary = build_executive_summary(actor_summaries, vector_scores,
                                                       vector_levels, tripwires_global)
            alignment_drift = score_alignment_drift(actor_summaries, tripwires_global,
                                                    commodity_pressure, crosstheater_amplifiers,
                                                    country='saudi_arabia')
            so_what = build_so_what_factor(actor_summaries, vector_scores, vector_levels,
                                           tripwires_global, commodity_pressure,
                                           alignment_drift=alignment_drift)
            # Sensor + contested-node signals fire on BOTH paths (Jul 2026):
            # the interpreter owns prose; the tracker owns its cross-reads.
            try:
                _extra, _, _ = _builtin_fallback_signals(
                    composite_score, composite_level, vector_scores, vector_levels,
                    actor_summaries, [], disaster_state)
                _have = {s.get('type') for s in top_signals if isinstance(s, dict)}
                for _sig in _extra:
                    if _sig.get('type') in ('natural_disaster_strain', 'contested_node') \
                            and _sig.get('type') not in _have:
                        top_signals.append(_sig)
            except Exception as _e:
                print(f'[KSA Rhetoric] cross-read append error: {str(_e)[:100]}')
            election_watch = None   # N/A -- absolute monarchy; no electoral cycle to watch
        except Exception as e:
            print(f"[KSA Rhetoric] Interpreter error: {str(e)[:200]}")
            traceback.print_exc()
            top_signals, executive_summary, so_what = _builtin_fallback_signals(
            composite_score, composite_level, vector_scores, vector_levels,
            actor_summaries, tripwires_global, disaster_state)
            election_watch = None
            alignment_drift = None
    else:
        top_signals, executive_summary, so_what = _builtin_fallback_signals(
            composite_score, composite_level, vector_scores, vector_levels,
            actor_summaries, tripwires_global, disaster_state)
        election_watch = None
        alignment_drift = None

    # ── Alignment-drift convergence signal (BRI inroad read) -> WHA BLUF / GPI ──
    if KSA_INTERPRETER_AVAILABLE and alignment_drift:
        _drift_sig = build_alignment_drift_top_signal(alignment_drift)
        if _drift_sig and not any(s.get('category') == 'alignment_drift' for s in top_signals):
            # Oct 18 2026: directly BELOW the tripwires, not above them -- the
            # axis reading is a consequence of the events, so events lead.
            _n_tw = sum(1 for s in top_signals if isinstance(s, dict) and s.get('type') == 'tripwire')
            top_signals = list(top_signals[:_n_tw]) + [_drift_sig] + list(top_signals[_n_tw:])


    # ── BLUF compatibility shim ──
    # wha_regional_bluf.py's _normalize_tracker_data() expects an integer
    # theatre_level (0-5) and a 0-100 theatre_score. Saudi Arabia emits a
    # categorical composite_level + a free-running composite_score; map
    # them so the regional BLUF can ingest Saudi Arabia cleanly alongside Cuba.
    LEVEL_TO_THEATRE_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
    raw_theatre_level = LEVEL_TO_THEATRE_INT.get(composite_level, 0)
    # Cap theatre_score at 100 — composite_score is unbounded by design
    theatre_score = min(100, int(composite_score))

    # ── L5 RESERVATION CONTRACT (v1.0.0 May 21 2026) ──
    # Compute L5 gate; cap theatre_level at L4 if raw is L5 but gate didn't fire.
    # Saudi Arabia scaffolds today — no severity-5 tripwires yet. Gate is silent until
    # weekend audit adds real L5-class triggers per axis.
    l5_gate = _compute_saudi_l5_gate(tripwires_global, actor_summaries, vector_scores)
    if raw_theatre_level >= 5 and not l5_gate['any']:
        theatre_level = 4
        l5_capped = True
        print(f"[KSA Rhetoric] L5 gate enforced: raw={raw_theatre_level} capped at L4 "
              f"(reason: {l5_gate['reason']})")
    else:
        theatre_level = raw_theatre_level
        l5_capped = False

    # ── Build label + signal text for BLUF consumption ──
    label_map_saudi_arabia = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning',
                      3: 'Direct Threat', 4: 'Coercion', 5: 'Active Crisis'}
    theatre_label = label_map_saudi_arabia.get(theatre_level, 'Monitoring')

    signal_text = _build_saudi_signal_text(
        theatre_level, theatre_score, vector_levels, actor_summaries, l5_capped,
    )

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success':               True,
        'country':               'saudi_arabia',
        'composite_score':       composite_score,
        'composite_level':       composite_level,
        # BLUF compatibility shim — see definitions above
        'theatre_level':         theatre_level,
        'theatre_score':         theatre_score,

        # ── L5 Reservation Contract fields (v1.0.0 May 21 2026) ──
        'theatre_label':         theatre_label,
        'signal_text_short':     signal_text['short'],
        'signal_text_long':      signal_text['long'],
        'l5_gate':               l5_gate,
        'raw_theatre_level':     raw_theatre_level,
        'l5_capped':             l5_capped,
        'source_class':          'contested_node',  # mixed-polarity node: pact anchor + Iran-wheel friction tier
        'vector_scores':         vector_scores,
        'vector_levels':         vector_levels,
        'actor_summaries':       actor_summaries,
        'tripwires_global':      tripwires_global,
        'commodity_pressure':    commodity_pressure,
        'crosstheater_amplifiers': crosstheater_amplifiers,
        'crosstheater_absent':     list(_CROSSTHEATER_ABSENT),
        'mecca_pact':              _mecca_pact_reading(actor_levels),   # v2.1.2: page reads this
        'claim_posture':         claim_posture,
        'telegram_available':    TELEGRAM_AVAILABLE,
        'top_signals':           top_signals,
        'executive_summary':     executive_summary,
        'so_what':               so_what,
        'alignment_drift':       alignment_drift,
        # Oct 18 2026: WHY GDELT returned what it did (throttled / budget / cache).
        'gdelt_health':          dict(_GDELT_HEALTH),
        'source_breakdown': {
            'telegram': len(telegram_articles),
            'rss':     len(rss_articles),
            'gdelt':   len(gdelt_articles),
            'newsapi': len(newsapi_articles),
            'brave':   len(brave_articles),
        },
        'total_articles_scanned': len(all_articles),
        'scan_time_seconds':      scan_time,
        'days_analyzed':          days,
        'last_updated':           datetime.now(timezone.utc).isoformat(),
        'cached':                 False,
        'version':                MODULE_VERSION,
    }

    save_cache(result)

    # ── Canonical history snapshot (May 22 2026 reconciled schema) ──
    # Universal fields read by wha_regional_bluf.prose_v2:
    #   theatre_level, theatre_score, scanned_at, red_lines_count
    # Plus Saudi Arabia-specific vector levels.
    try:
        _redis_lpush_trim(HISTORY_KEY, {
            'theatre_level':       theatre_level,
            'theatre_score':       theatre_score,
            'scanned_at':          result.get('last_updated') or datetime.now(timezone.utc).isoformat(),
            'red_lines_count':     len(tripwires_global),
            # Oct 18 2026 FIX: these four fields used to be kinetic_afpak,
            # repression_rights, external_friction, illicit_economy --
            # AFGHANISTAN vectors this tracker has never had, so every history
            # entry since July recorded None x4 and none of its real vectors.
            # Now: whatever VECTOR_GROUPS defines (the stability-page gauge
            # contract), so the snapshot can never drift from the vectors again.
            **{v: vector_levels.get(v) for v in VECTOR_GROUPS},
        }, max_len=336)
    except Exception as e:
        print(f"[KSA Rhetoric] History snapshot write failed: {e}")

    print(f"[KSA Rhetoric] ✅ Scan complete in {scan_time}s — composite {composite_level} ({composite_score})")
    return result


# ============================================
# BACKGROUND REFRESH LOOP
# ============================================
def _background_refresh_loop():
    """Periodic refresh — initial 90s delay, then every BACKGROUND_REFRESH_HOURS."""
    global _background_scan_running
    time.sleep(INITIAL_SCAN_DELAY_SECONDS)
    while True:
        try:
            with _background_scan_lock:
                if _background_scan_running:
                    time.sleep(60)
                    continue
                _background_scan_running = True
            try:
                print("[KSA Rhetoric] Background refresh starting...")
                scan_saudi_rhetoric(force=True, days=7)
                print("[KSA Rhetoric] Background refresh complete.")
            finally:
                with _background_scan_lock:
                    _background_scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print(f"[KSA Rhetoric] Background loop error: {e}")
            time.sleep(600)


def _start_background_refresh():
    t = threading.Thread(target=_background_refresh_loop, daemon=True, name='SaudiRhetoricBG')
    t.start()
    print(f"[KSA Rhetoric] Background refresh thread started (initial delay {INITIAL_SCAN_DELAY_SECONDS}s)")


# ============================================
# FLASK ENDPOINTS
# ============================================
def register_saudi_rhetoric_routes(app, start_background=True):
    """Register Saudi Arabia rhetoric endpoints on a Flask app + start background refresh."""
    from flask import jsonify, request

    @app.route('/api/rhetoric/saudi_arabia', methods=['GET', 'OPTIONS'])
    def api_saudi_arabia_rhetoric():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = request.args.get('refresh', '').lower() in ('true', '1', 'yes')

        cached = load_cache()
        if cached and is_cache_fresh(cached) and not force:
            cached['cached'] = True
            return jsonify(cached)

        # Cache miss or force refresh — return cached (if any) and trigger background scan
        if cached and not force:
            cached['cached'] = True
            cached['stale'] = True
            # Trigger background scan if not already running
            with _background_scan_lock:
                if not _background_scan_running:
                    threading.Thread(
                        target=lambda: scan_saudi_rhetoric(force=True, days=7),
                        daemon=True,
                    ).start()
            return jsonify(cached)

        # No cache at all — do synchronous scan (slow!)
        result = scan_saudi_rhetoric(force=force, days=7)
        return jsonify(result)

    @app.route('/api/rhetoric/saudi_arabia/debug', methods=['GET'])
    def api_saudi_arabia_rhetoric_debug():
        """Diagnostic — config snapshot + cache freshness."""
        cached = load_cache()
        return jsonify({
            'version':                  MODULE_VERSION,
            'actor_count':              len(ACTORS),
            'actors':                   list(ACTORS.keys()),
            'vector_count':             len(VECTOR_GROUPS),
            'vectors':                  list(VECTOR_GROUPS.keys()),
            'rss_feeds':                len(RSS_FEEDS),
            'gdelt_queries_en':         len(GDELT_QUERIES_EN),
            'gdelt_queries_es':         len(GDELT_QUERIES_ES),
            'tripwires':                len(TRIPWIRES),
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured':       bool(NEWSAPI_KEY),
            'brave_configured':         bool(BRAVE_API_KEY),
            'commodity_fingerprint':    COMMODITY_FINGERPRINT_AVAILABLE,
            'interpreter_available':    KSA_INTERPRETER_AVAILABLE,
            'cache_present':            cached is not None,
            'cache_fresh':              is_cache_fresh(cached) if cached else False,
            'cache_age_hours':          None if not cached else round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(cached.get('cached_at', '2020-01-01T00:00:00+00:00'))).total_seconds() / 3600, 2
            ) if cached.get('cached_at') else None,
            'last_scan_started_at':     _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running':       _background_scan_running,
        })

    print("[KSA Rhetoric] ✅ Endpoints registered:")
    print("  GET  /api/rhetoric/saudi_arabia")
    print("  GET  /api/rhetoric/saudi_arabia/debug")

    if start_background:
        _start_background_refresh()
    else:
        print("[KSA Rhetoric] ℹ️ Background refresh disabled on this instance")


print("[KSA Rhetoric] Module loaded.")
