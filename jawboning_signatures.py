"""
================================================================================
jawboning_signatures.py — Asifah Analytics
================================================================================
JAWBONING SIGNATURES — Phase 3 shared primitive.

Models leader-level rhetorical pressure as a first-class, direction-aware
platform primitive. Where the absorption module answers "is upstream pressure
being absorbed into downstream rhetoric?", this module answers a complementary
question:

  "Is a leader using public rhetoric to move a market, sector, or country's
   behavior — and in which DIRECTION is the pressure flowing?"

TWO DIRECTIONAL MODES — single catalog, dual semantics
--------------------------------------------------------------------------------

  COMMAND jawboning (top-down):
    The leader is CREATING pressure outward. A command-node head-of-state
    publicly pressures a market, sector, foreign government, or company to
    move in a desired direction, without firing the formal policy lever.
    Example: Trump telling US oil companies to lower prices. Trump threatening
    tariffs on Mexico to extract migration concessions. Trump pressuring the
    Fed to lower rates.

    Pressure flow:  LEADER → TARGET
    Cross-theater impact:  HIGH (US command-node rhetoric ripples into Iran,
                                  China, Russia, Mexico, Cuba, Greenland
                                  trackers simultaneously)

  ABSORBER jawboning (bottom-up / inward):
    Upstream pressure is being absorbed by the leader through a domestic ask.
    The leader is MANAGING incoming pressure by redirecting it toward citizens
    or domestic actors. The rhetoric is compensatory, not coercive.
    Example: Modi telling Indian households to buy less gold *because* RBI is
    losing FX reserves *because* of Hormuz pressure on oil imports. Modi's
    austerity rhetoric absorbs upstream economic stress into a domestic ask.

    Pressure flow:  UPSTREAM STRESSOR → LEADER → DOMESTIC COMPENSATION
    Cross-theater impact:  MEDIUM (signals which downstream country is
                                    currently under stress from which
                                    upstream source)

CACHING CONTRACT — Asifah platform principle
--------------------------------------------------------------------------------

  Every endpoint a user can hit serves Redis-cached data on first hit.
  Live computation is the fallback path, not the default. Users never wait
  for a fresh scan unless they explicitly opt in.

  This module follows the contract in three ways:

  1. CATALOG HYDRATION:  At module load, the full catalog is written to
                          Redis (full blob + per-entry keys). First production
                          deploy populates the cache automatically.

  2. CATALOG READS:       read_jawboning_signature() and list_jawboning_signatures()
                          ALWAYS check Redis first, fall back to the in-memory
                          static catalog only on cache miss (e.g., fresh Redis
                          instance, or expired TTL).

  3. FINGERPRINT WRITES:  Detector module writes 'jawboning:{dir}:{country}:
                          {target}' keys with 24h TTL. Cross-theater readers
                          (Iran, China, Cuba, Russia trackers) read these
                          directly — no detector roundtrip needed.

ARCHITECTURE
--------------------------------------------------------------------------------

  Phase 1 (today):     Static nested catalog (JAWBONING_SIGNATURES_STATIC)
                       hand-curated. 13 entries at launch:
                         - 11 Trump command signatures (4 domestic, 6 foreign-
                           policy, 1 strategic partner)
                         - 2 Modi absorber signatures (migrated from inline
                           computation in rhetoric_tracker_india.py)

  Phase 2 (detection): jawboning_detector.py reads this catalog, applies the
                       trigger-keyword matching against per-leader actor
                       rhetoric, and writes Redis fingerprints.

  Phase 3 (cross-     Iran, China, Russia, Cuba, Greenland, Mexico (future),
   theater reads):    Saudi (future) trackers read the relevant Trump command
                      fingerprints and amplify their own actor scores.

  Phase 4 (Black      Black Swan module consumes ALL jawboning fingerprints
   Swan inputs):      as Origin-axis upstream-signal inputs.

USAGE
--------------------------------------------------------------------------------

  Read a single signature (Redis-first, static fallback):
    from jawboning_signatures import read_jawboning_signature
    sig = read_jawboning_signature('trump_on_iran')

  List signatures by leader / country / direction:
    from jawboning_signatures import (
        get_signatures_by_leader,
        get_signatures_by_country,
        get_signatures_by_direction,
    )

  Endpoints:
    GET /api/jawboning/signatures              → full catalog (Redis-cached)
    GET /api/jawboning/signatures/<sig_id>     → single entry (Redis-cached)
    GET /api/jawboning/signatures?leader=trump → filtered by leader

  Register in app.py:
    from jawboning_signatures import register_jawboning_signatures_endpoints
    register_jawboning_signatures_endpoints(app)

v1.0.0 — May 14 2026 · Path B Architectural Primitive
================================================================================
"""

import os
import json
import requests
from datetime import datetime, timezone


# ============================================================================
# REDIS CONFIG  (mirrors absorption_signatures.py pattern)
# ============================================================================

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')

# Catalog itself is static and rarely changes; cached at long TTL.
JAWBONING_CATALOG_TTL_HOURS = 168   # 7 days — catalog rarely changes

# Fingerprint TTL — how long a "Trump is currently jawboning X" flag stays TRUE
# in Redis after detection. 24h means a single afternoon of rhetoric persists
# through the next news cycle for cross-theater consumers to read.
JAWBONING_FINGERPRINT_TTL_HOURS = 24


# ============================================================================
# REDIS KEY HELPERS
# ============================================================================

def _catalog_redis_key_single(signature_id):
    """Redis key for a single catalog entry."""
    return f"jawboning_catalog:single:{signature_id}"


def _catalog_redis_key_full():
    """Redis key for the full catalog blob (used by list endpoint)."""
    return "jawboning_catalog:full"


def _fingerprint_redis_key(direction, country_id, target_key):
    """
    Canonical Redis key for an active jawboning fingerprint.

    Examples:
      jawboning:command:us:on_iran
      jawboning:command:us:on_oil
      jawboning:absorber:india:on_gold
      jawboning:absorber:india:on_austerity

    Cross-theater consumers (Iran tracker, China tracker, etc.) read these
    keys to know whether they're currently being jawboned. Written by
    jawboning_detector.py, read by every tracker.
    """
    return f"jawboning:{direction}:{country_id}:{target_key}"


# ============================================================================
# REDIS I/O — defensive, never crashes the caller on a Redis hiccup
# ============================================================================

def _redis_get(key):
    """GET a key from Upstash Redis REST. Returns parsed JSON or None on miss/error."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        result = r.json().get('result')
        if result is None:
            return None
        # Upstash returns JSON-stringified values; parse defensively
        try:
            return json.loads(result)
        except (TypeError, ValueError):
            return result
    except Exception as e:
        print(f"[Jawboning Signatures] Redis GET error for {key}: {e}")
        return None


def _redis_set(key, value, ttl_seconds=None):
    """SET a key in Upstash Redis REST with optional TTL. Silent on failure."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value) if not isinstance(value, str) else value
        url = f"{UPSTASH_REDIS_URL}/set/{key}"
        if ttl_seconds:
            url += f"?EX={ttl_seconds}"
        r = requests.post(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            data=payload,
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[Jawboning Signatures] Redis SET error for {key}: {e}")
        return False


# ============================================================================
# THE STATIC CATALOG — nested by direction
# ============================================================================
#
# Per-entry schema (every entry has all of these fields):
#   leader_id              str   — canonical leader identifier
#   country_id             str   — ISO-style country code (us, india, etc.)
#   direction              str   — 'command' or 'absorber' (mirrors parent key)
#   target_sector          str   — short label for the thing being jawboned
#   target_key             str   — short snake_case key used in the Redis
#                                  fingerprint (jawboning:{dir}:{country}:{target_key})
#   target_actors          list  — who/what receives the pressure (command) OR
#                                  who/what absorbs the pressure (absorber)
#   trigger_keywords       list  — English phrases that signal the rhetoric
#   trigger_keywords_native list — same in non-English where relevant
#   mechanism              str   — the causal channel
#   upstream_stressors     list  — (absorber only) what's driving the absorber
#                                  to speak this way; empty list for command
#   cross_theater_writes   list  — Redis fingerprint keys this signature writes
#   pattern_basis          str   — 'analyst_curated' | 'auto_learned'
#   confidence             str   — 'high' | 'medium' | 'speculative'
#   historical_anchors     list  — known real-world events matching this pattern
#   analyst_summary_template str — diplomat-grade prose, plain language
#                                  (may interpolate {forward_indicators_joined})
#   forward_indicators     list  — what to watch for if this signature fires
# ============================================================================

JAWBONING_SIGNATURES_STATIC = {
    'command': {

        # ════════════════════════════════════════════════════════════════════
        # DOMESTIC / ECONOMIC COMMAND JAWBONING (4)
        # ════════════════════════════════════════════════════════════════════

        'trump_on_oil': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'oil_prices',
            'target_key':      'on_oil',
            'target_actors':   ['us_oil_companies', 'opec', 'saudi_arabia', 'us_drillers'],
            'trigger_keywords': [
                'drill baby drill', 'drill, baby, drill',
                'gas prices', 'gasoline prices', 'lower oil', 'cheaper oil',
                'opec', 'opec+', 'oil prices', 'crude prices',
                'pump prices', 'pump price', 'fuel prices',
                'energy dominance', 'unleash american energy',
                'open the spigot', 'pump more oil',
            ],
            'trigger_keywords_native': [],
            'mechanism': 'production_increase_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_oil',
                'jawboning:command:us:on_saudi',  # often paired
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'April 2018 OPEC tweet ("Looks like OPEC is at it again")',
                'July 2019 oil-price tweets',
                'November 2024 post-election OPEC pressure',
            ],
            'analyst_summary_template': (
                "Trump is publicly pressuring oil markets to lower prices. The rhetoric "
                "operates as a free option: rhetorical pressure first, formal policy "
                "leverage (SPR releases, OPEC sanctions, Saudi diplomatic pressure) held "
                "in reserve. Cross-theater impact is HIGH — every oil-dependent country "
                "tracker should expect amplified signals while this rhetoric is active. "
                "Watch for: {forward_indicators_joined}."
            ),
            'forward_indicators': [
                'SPR release announcement',
                'Saudi diplomatic outreach (Trump-MBS call)',
                'OPEC+ emergency meeting or production-increase pledge',
                'US drilling permit acceleration',
                'WTI/Brent spread movement',
            ],
        },

        'trump_on_fed': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'monetary_policy',
            'target_key':      'on_fed',
            'target_actors':   ['federal_reserve', 'jerome_powell', 'fomc'],
            'trigger_keywords': [
                'jerome powell', 'powell', 'fed chair',
                'federal reserve', 'the fed',
                'lower rates', 'cut rates', 'rate cut',
                'too high', 'interest rates',
                'monetary policy', 'tight money',
                'fire powell', 'replace powell',
            ],
            'trigger_keywords_native': [],
            'mechanism': 'monetary_easing_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_fed',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'July 2019 "Powell is killing us" tweets',
                'August 2019 "Who is our bigger enemy, Powell or Xi?" tweet',
                'November 2024 transition-period rate-cut pressure',
            ],
            'analyst_summary_template': (
                "Trump is publicly pressuring the Federal Reserve to ease monetary "
                "policy. Note: presidential pressure on independent central banks is "
                "historically rare and signals either real economic stress, electoral "
                "calculation, or both. DXY effects ripple globally — every emerging "
                "market currency tracker should expect volatility. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'FOMC dot-plot revisions',
                'Powell public response (rare but historically pointed)',
                'DXY weakening on rhetoric alone',
                'EM currency stress (TRY, ARS, BRL especially)',
                'Gold price reaction',
            ],
        },

        'trump_on_tariffs': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'trade_policy',
            'target_key':      'on_tariffs',
            'target_actors':   ['china', 'mexico', 'canada', 'eu', 'specific_industries'],
            'trigger_keywords': [
                'tariffs', 'tariff', 'reciprocal tariff',
                '25 percent', '25%', '50 percent', '50%', '100 percent', '100%',
                'levy', 'levies',
                'trade deal', 'trade war',
                'unfair trade', 'fair trade',
                'made in america', 'bring jobs back',
            ],
            'trigger_keywords_native': [],
            'mechanism': 'coercive_bilateral_leverage',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_tariffs',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'March 2018 steel/aluminum tariffs',
                'May 2019 Mexico tariff threat (migration leverage)',
                'February 2025 Canada/Mexico/China tariff round',
            ],
            'analyst_summary_template': (
                "Trump is using tariff threats as coercive bilateral leverage. The "
                "rhetoric often targets a country to extract concessions on a "
                "non-trade issue (migration, fentanyl, geopolitical alignment). "
                "Equity markets typically price the threat in stages: announcement → "
                "negotiation → resolution OR escalation. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'Target-country leader phone call or visit',
                'Section 232 / Section 301 formal proceedings',
                'Specific tariff percentage announcement',
                'Industry-association lobbying response',
                'Counter-tariff threats from target country',
            ],
        },

        'trump_on_companies': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'corporate_pressure',
            'target_key':      'on_companies',
            'target_actors':   ['boeing', 'apple', 'big_pharma', 'big_tech', 'gm', 'ford'],
            'trigger_keywords': [
                'boeing', 'apple', 'tim cook',
                'pharma', 'drug prices', 'lower drug prices',
                'big tech', 'meta', 'zuckerberg',
                'ford', 'general motors',
                'made in china', 'move production',
                'bring back jobs',
            ],
            'trigger_keywords_native': [],
            'mechanism': 'firm_specific_jawboning',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_companies',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'medium',
            'historical_anchors': [
                'December 2016 Carrier-Indiana intervention',
                'December 2018 GM Lordstown plant closure tweets',
                'May 2025 Apple-India production tweets',
            ],
            'analyst_summary_template': (
                "Trump is publicly pressuring a specific company or industry. Firm-"
                "specific jawboning is idiosyncratic but historically market-moving for "
                "the targeted ticker. Broader sector effects are usually muted. Confidence "
                "is medium because volume of firm-targeted rhetoric is high but signal-"
                "to-noise varies. Watch for: {forward_indicators_joined}."
            ),
            'forward_indicators': [
                'Targeted ticker pre-market movement',
                'CEO public response',
                'Regulatory hint (SEC, FTC, DOJ)',
                'Specific policy threat (tariff, investigation, contract loss)',
                'Industry-wide spillover to peers',
            ],
        },

        # ════════════════════════════════════════════════════════════════════
        # FOREIGN-POLICY COMMAND JAWBONING (6)
        # ════════════════════════════════════════════════════════════════════

        'trump_on_china': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'china_policy',
            'target_key':      'on_china',
            'target_actors':   ['xi_jinping', 'china_government', 'taiwan', 'semiconductor'],
            'trigger_keywords': [
                'xi jinping', 'president xi', 'china',
                'beijing', 'ccp', 'chinese communist party',
                'taiwan', 'taiwan strait',
                'semiconductors', 'chips', 'chip war',
                'rare earth', 'rare earths',
                'tiktok',
                'south china sea',
                'trade deal with china',
            ],
            'trigger_keywords_native': [
                '中国', '习近平', '台湾', '北京',  # Chinese tracker will surface these
            ],
            'mechanism': 'great_power_strategic_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_china',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'May 2019 trade war escalation',
                'August 2020 TikTok ban executive order',
                'January 2025 chip restrictions',
            ],
            'analyst_summary_template': (
                "Trump is applying public rhetorical pressure to China. Great-power "
                "jawboning has the highest cross-theater impact of any signal class — "
                "China's response options span trade, Taiwan policy, rare earths, "
                "semiconductors, and currency. The Asia rhetoric tracker should expect "
                "amplified PLA + MOFA scoring. Watch for: {forward_indicators_joined}."
            ),
            'forward_indicators': [
                'PLA exercises near Taiwan',
                'Chinese MOFA press conference response',
                'Rare-earth export restriction signals',
                'Yuan reference-rate fixings',
                'Chinese delegation visit announcement (Treasury or USTR)',
            ],
        },

        'trump_on_iran': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'iran_policy',
            'target_key':      'on_iran',
            'target_actors':   ['iran_government', 'irgc', 'khamenei', 'iranian_proxies'],
            'trigger_keywords': [
                'iran', 'iranian regime', 'tehran',
                'khamenei', 'ayatollah',
                'maximum pressure', 'maximum-pressure',
                'iran deal', 'jcpoa', 'nuclear deal',
                'iranian nuclear', 'iran nuclear',
                'sanctions on iran', 'snap-back sanctions',
                'houthis', 'hezbollah', 'iranian proxies',
                'iran will not have a nuclear weapon',
            ],
            'trigger_keywords_native': [
                'إيران', 'طهران',  # Arabic
                'ایران', 'تهران',  # Farsi
            ],
            'mechanism': 'maximum_pressure_signaling',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_iran',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'May 2018 JCPOA withdrawal announcement',
                'January 2020 Soleimani strike rhetoric',
                'February 2025 maximum-pressure restoration',
            ],
            'analyst_summary_template': (
                "Trump is signaling escalated US pressure on Iran. Iranian leadership "
                "tends to read this rhetoric as a leading indicator of formal policy "
                "moves (sanctions, asset freezes, IRGC designations, or kinetic options). "
                "ME backend trackers should expect amplified IRGC + foreign-policy actor "
                "scoring; Hormuz/BAM friction-tax risk rises. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'IRGC public response (Salami, Naini)',
                'Iranian Supreme Council statement',
                'Hormuz transit interference reports',
                'Houthi/Hezbollah rhetoric escalation',
                'Israeli posture changes (Mossad/IDF leaks)',
                'OFAC sanctions designations',
            ],
        },

        'trump_on_russia_ukraine': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'russia_ukraine_war',
            'target_key':      'on_russia_ukraine',
            'target_actors':   ['putin', 'zelensky', 'russia_government', 'ukraine_government', 'nato'],
            'trigger_keywords': [
                'putin', 'vladimir putin', 'russia',
                'zelensky', 'zelenskyy', 'ukraine',
                'end the war', 'peace deal',
                'nato funding', 'nato allies', 'nato spending',
                '2 percent', '5 percent', 'gdp on defense',
                'ceasefire ukraine',
                'frozen conflict',
                'minerals deal',
            ],
            'trigger_keywords_native': [
                'путин', 'россия', 'украина',  # Russian/Ukrainian
            ],
            'mechanism': 'peace_deal_leverage_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_russia_ukraine',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'July 2018 Helsinki press conference',
                'February 2025 Oval Office Zelensky exchange',
                'March 2025 minerals-deal pressure cycle',
            ],
            'analyst_summary_template': (
                "Trump is applying public pressure to either or both sides of the "
                "Russia-Ukraine war. Bidirectional leverage rhetoric (pressure on "
                "Kyiv AND Moscow simultaneously) is the distinctive Trump pattern, "
                "differing from prior US policy. Europe backend trackers should expect "
                "amplified Kremlin + Bankova actor scoring; NATO funding rhetoric "
                "ripples into European defense-industrial trackers. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'Kremlin spokesman Peskov response',
                'Bankova (Ukrainian presidency) statement',
                'Stoltenberg/Rutte (NATO SecGen) public reaction',
                'European leader emergency consultations',
                'US arms-shipment announcement or pause',
                'Black Sea grain/shipping disruption',
            ],
        },

        'trump_on_mexico': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'mexico_policy',
            'target_key':      'on_mexico',
            'target_actors':   ['mexico_government', 'sheinbaum', 'border_patrol', 'cartels'],
            'trigger_keywords': [
                'mexico', 'mexican government',
                'sheinbaum', 'amlo',
                'border', 'southern border',
                'caravan', 'caravans',
                'deportation', 'deportations',
                'cartels', 'cartel', 'fentanyl',
                'remain in mexico',
                'mexico tariff', 'mexican tariff',
            ],
            'trigger_keywords_native': [
                'méxico', 'frontera',  # Spanish
            ],
            'mechanism': 'migration_leverage_via_tariff_threat',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_mexico',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'May 2019 Mexico tariff threat (migration leverage)',
                'November 2024 Day-1 tariff announcement',
                'February 2025 fentanyl-tariff lever',
            ],
            'analyst_summary_template': (
                "Trump is applying public pressure to Mexico. The signature pattern is "
                "tariff threats deployed as migration/fentanyl leverage — rhetorical "
                "pressure first, formal tariff invocation second. The peso reacts within "
                "minutes of credible rhetoric. WHA backend should expect amplified "
                "Sheinbaum administration scoring. Watch for: {forward_indicators_joined}."
            ),
            'forward_indicators': [
                'MXN/USD peso reaction',
                'Sheinbaum public response',
                'National Guard border deployment announcement',
                'Cartel-designation rhetoric (FTO listing)',
                'Specific tariff percentage and effective date',
            ],
        },

        'trump_on_cuba': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'cuba_policy',
            'target_key':      'on_cuba',
            'target_actors':   ['cuba_government', 'diaz_canel', 'cuban_diaspora'],
            'trigger_keywords': [
                'cuba', 'cuban regime',
                'havana', 'diaz-canel', 'díaz-canel',
                'cuba sanctions', 'libertad act',
                'cuban-american', 'cuban americans',
                'state sponsor of terror', 'sst',
                'guantanamo',
                'communist regime',
            ],
            'trigger_keywords_native': [
                'cuba', 'la habana',  # Spanish
            ],
            'mechanism': 'sanctions_and_regime_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_cuba',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'June 2017 Cuba policy directive (rollback of Obama opening)',
                'January 2021 SST re-designation',
                'February 2025 SST re-listing',
            ],
            'analyst_summary_template': (
                "Trump is applying public pressure to the Cuban regime. The signature "
                "pattern is sanctions tightening + Cuban-diaspora-facing rhetoric — both "
                "as a coercive lever on Havana AND as domestic Florida-electorate "
                "signaling. WHA Cuba tracker should expect amplified regime + diaspora "
                "actor scoring; migration-surge signals often follow. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'OFAC Cuba-specific sanctions designation',
                'Cuban government MINREX response',
                'Migration-surge signals (rafter departures, MX-US flows)',
                'Russia/China/Iran-Cuba axis activation',
                'Florida congressional-delegation statements',
            ],
        },

        'trump_on_greenland': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'greenland_strategic',
            'target_key':      'on_greenland',
            'target_actors':   ['denmark_government', 'greenland_government', 'nato_arctic'],
            'trigger_keywords': [
                'greenland', 'kalaallit nunaat',
                'denmark', 'danish government',
                'frederiksen',
                'thule', 'pituffik',
                'arctic strategy', 'arctic council',
                'buy greenland', 'acquire greenland',
                'rare earth greenland',
                'national security greenland',
            ],
            'trigger_keywords_native': [
                'grønland',  # Danish
            ],
            'mechanism': 'strategic_asset_sovereignty_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_greenland',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'August 2019 "buy Greenland" proposal',
                'January 2025 transition-period Greenland acquisition rhetoric',
                'March 2025 Vance Greenland visit',
            ],
            'analyst_summary_template': (
                "Trump is applying public pressure regarding Greenland's strategic status "
                "vis-à-vis the United States. This is a NATO-internal sovereignty-"
                "challenge signal — the first such pattern between two NATO members in "
                "the alliance's history. Europe Arctic trackers should expect amplified "
                "Denmark + Greenland self-determination scoring. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'Danish PM Frederiksen direct response',
                'Greenland Premier statement on sovereignty',
                'NATO SecGen comment (sovereignty within alliance)',
                'Russian/Chinese Arctic posture changes',
                'US military Arctic deployment signals',
                'Rare-earth/mineral resource agreement language',
            ],
        },

        # ════════════════════════════════════════════════════════════════════
        # STRATEGIC PARTNER JAWBONING (1)
        # ════════════════════════════════════════════════════════════════════

        'trump_on_saudi': {
            'leader_id':       'trump',
            'country_id':      'us',
            'direction':       'command',
            'target_sector':   'saudi_strategic',
            'target_key':      'on_saudi',
            'target_actors':   ['mbs', 'saudi_government', 'opec', 'aramco'],
            'trigger_keywords': [
                'saudi', 'saudi arabia',
                'mbs', 'mohammed bin salman', 'crown prince',
                'riyadh',
                'aramco',
                'saudi defense', 'saudi defence', 'arms sales to saudi',
                'saudi-iran', 'normalization',
                'abraham accords', 'abraham accord',
                'saudi opec',
            ],
            'trigger_keywords_native': [
                'السعودية', 'الرياض', 'بن سلمان',  # Arabic
            ],
            'mechanism': 'strategic_partner_alignment_pressure',
            'upstream_stressors': [],
            'cross_theater_writes': [
                'jawboning:command:us:on_saudi',
                'jawboning:command:us:on_oil',  # bidirectional with oil
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'May 2017 first foreign visit to Riyadh',
                'November 2018 Khashoggi response (rhetorical alignment with Saudi)',
                'May 2025 Riyadh visit + Abraham Accords expansion rhetoric',
            ],
            'analyst_summary_template': (
                "Trump is publicly engaging Saudi Arabia in strategic-partner mode. The "
                "signature differs from coercive command jawboning: it's alignment-"
                "pressure rather than threat-pressure. Saudi response options span oil "
                "production, Iran normalization talks, Israel-Saudi normalization (Abraham "
                "Accords expansion), and defense procurement. ME backend should expect "
                "amplified Riyadh + MBS scoring; bidirectional reads with oil rhetoric. "
                "Watch for: {forward_indicators_joined}."
            ),
            'forward_indicators': [
                'OPEC+ production guidance shift',
                'Saudi-Israel normalization progress signals',
                'Defense-procurement announcements',
                'Iran-Saudi diplomatic channel activity',
                'Aramco strategic-investment announcements',
            ],
        },

    },
    'absorber': {},   # Filled in Chunk 1C — 2 Modi entries (migrated)
}
