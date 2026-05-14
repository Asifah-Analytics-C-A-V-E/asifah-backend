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
    'absorber': {

        # ════════════════════════════════════════════════════════════════════
        # MODI ABSORBER JAWBONING (2) — migrated from rhetoric_tracker_india.py
        # ════════════════════════════════════════════════════════════════════
        #
        # NOTE for the detector module:
        # The live India tracker also gates these flags on `pmo.get('level', 0) >= 2`
        # — i.e., the trigger keywords ONLY fire the flag when the PMO actor
        # cluster is itself active at level 2+. That gate is detection logic,
        # not signature definition, so it lives in jawboning_detector.py.
        # When Phase 4 runs the dual-track comparison, the detector must apply
        # this gate to match inline output. Do not move the gate into the
        # catalog.
        # ════════════════════════════════════════════════════════════════════

        'modi_on_gold': {
            'leader_id':       'modi',
            'country_id':      'india',
            'direction':       'absorber',
            'target_sector':   'gold_demand',
            'target_key':      'on_gold',
            'target_actors':   ['indian_households', 'jewellery_buyers', 'wedding_season_spending'],
            'trigger_keywords': [
                'gold', 'bullion', 'jewellery', 'jewelry',
                'wedding gold',
            ],
            'trigger_keywords_native': [
                'सोना', 'सोने',  # Hindi
            ],
            'mechanism': 'domestic_demand_suppression_via_civic_appeal',
            'upstream_stressors': [
                'hormuz_pressure',
                'iran_irgc_active',
                'rbi_fx_pressure',
                'oil_import_bill_stress',
            ],
            'cross_theater_writes': [
                'jawboning:absorber:india:on_gold',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'May 2026 Modi-on-gold detection (live, validated against Reuters)',
                'November 2016 demonetization era gold-demand rhetoric',
                'July 2022 Mann ki Baat gold-import commentary',
            ],
            'analyst_summary_template': (
                "Modi is publicly urging Indian households to reduce gold demand. The "
                "pattern is absorber-class: upstream stress on India's FX reserves "
                "(typically from oil import pressure tied to Hormuz volatility) is "
                "redirected as a domestic civic appeal rather than a formal policy "
                "intervention. Free option: rhetoric first, formal levers (import duty, "
                "monetization scheme push) held in reserve. Asia tracker should expect "
                "amplified PMO + Economic Statecraft scoring. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'RBI FX-reserve weekly disclosure',
                'Customs duty on gold-import announcement',
                'Sovereign Gold Bond scheme re-launch',
                'Wedding-season spending advisories',
                'Mint/Hindu Business Line gold-import commentary',
            ],
        },

        'modi_on_austerity': {
            'leader_id':       'modi',
            'country_id':      'india',
            'direction':       'absorber',
            'target_sector':   'discretionary_spending',
            'target_key':      'on_austerity',
            'target_actors':   ['indian_households', 'middle_class_consumers'],
            'trigger_keywords': [
                'austerity', 'discretionary', 'belt-tighten',
                'belt tightening', 'belt-tightening',
                'savings', 'frugal', 'restraint',
            ],
            'trigger_keywords_native': [
                'मितव्ययिता', 'किफायत',  # Hindi: thrift, frugality
            ],
            'mechanism': 'domestic_consumption_restraint_via_civic_appeal',
            'upstream_stressors': [
                'broader_economic_stress',
                'inflation_pressure',
                'fx_reserve_pressure',
            ],
            'cross_theater_writes': [
                'jawboning:absorber:india:on_austerity',
            ],
            'pattern_basis':   'analyst_curated',
            'confidence':      'high',
            'historical_anchors': [
                'May 2026 Modi austerity rhetoric (live, validated against Reuters)',
                'COVID-era "vocal for local" + frugality framing',
            ],
            'analyst_summary_template': (
                "Modi is publicly urging Indian households to reduce discretionary "
                "spending broadly — a wider 'tighten your belt' framing distinct from "
                "the gold-specific jawboning signature. Reuters has validated this as "
                "a separate rhetorical mode in market commentary. Pattern indicates "
                "broader economic stress absorption rather than commodity-specific "
                "pressure. Asia tracker should expect amplified PMO scoring; pairs "
                "frequently with modi_on_gold when FX/oil stress is acute. Watch for: "
                "{forward_indicators_joined}."
            ),
            'forward_indicators': [
                'CPI/WPI inflation print',
                'FMCG sector consumption commentary',
                'Festival-season spending advisories',
                'Mann ki Baat thematic content',
                'Finance Minister supporting statements',
            ],
        },

    },
}


# ============================================================================
# CACHE HYDRATION — populate Redis from the static catalog
# ============================================================================
#
# Per the Asifah caching contract: user-facing endpoints must serve Redis-
# cached data on first hit. To make that possible, the static catalog defined
# above is written to Redis at module-import time (i.e., on every fresh
# deploy / process start). Two key shapes are written:
#
#   1. jawboning_catalog:full           — the entire nested catalog as JSON
#   2. jawboning_catalog:single:<sig_id> — one key per signature for fast lookup
#
# TTL is 7 days. The catalog rarely changes; if a new entry is added and
# pushed to production, the module reload re-hydrates Redis with the new
# entries automatically.
# ============================================================================

def hydrate_catalog_to_redis():
    """
    Write the full static catalog to Redis. Called automatically at module
    import time (see bottom of file) and can be called manually via the
    /api/jawboning/signatures/hydrate endpoint.

    Returns dict with hydration statistics for logging.
    """
    ttl_seconds = JAWBONING_CATALOG_TTL_HOURS * 3600
    stats = {'full_blob': False, 'single_entries': 0, 'failures': 0}

    # Write the full catalog blob (used by /api/jawboning/signatures list endpoint)
    if _redis_set(_catalog_redis_key_full(), JAWBONING_SIGNATURES_STATIC, ttl_seconds):
        stats['full_blob'] = True
    else:
        stats['failures'] += 1

    # Write each signature as its own key (used by /api/jawboning/signatures/<id>)
    for direction, signatures in JAWBONING_SIGNATURES_STATIC.items():
        for sig_id, sig_data in signatures.items():
            if _redis_set(_catalog_redis_key_single(sig_id), sig_data, ttl_seconds):
                stats['single_entries'] += 1
            else:
                stats['failures'] += 1

    return stats


# ============================================================================
# READ FUNCTIONS — Redis-first, static-dict fallback
# ============================================================================

def read_jawboning_signature(signature_id):
    """
    Return a single signature by ID. Redis-first; falls back to the static
    catalog if Redis is unavailable or the key is missing.

    Returns None if the signature_id doesn't exist anywhere.
    """
    # Try Redis first
    cached = _redis_get(_catalog_redis_key_single(signature_id))
    if cached:
        return cached

    # Fallback: scan static catalog
    for direction in ('command', 'absorber'):
        if signature_id in JAWBONING_SIGNATURES_STATIC.get(direction, {}):
            return JAWBONING_SIGNATURES_STATIC[direction][signature_id]

    return None


def list_jawboning_signatures():
    """
    Return the full catalog (nested by direction). Redis-first; falls back to
    the static catalog if Redis is unavailable.
    """
    cached = _redis_get(_catalog_redis_key_full())
    if cached:
        return cached
    return JAWBONING_SIGNATURES_STATIC


def get_signatures_by_leader(leader_id):
    """
    Return all signatures for a given leader, flat list. Reads via
    list_jawboning_signatures() so it inherits the Redis-first behavior.
    """
    catalog = list_jawboning_signatures()
    results = []
    for direction in ('command', 'absorber'):
        for sig_id, sig_data in catalog.get(direction, {}).items():
            if sig_data.get('leader_id') == leader_id:
                results.append({'signature_id': sig_id, **sig_data})
    return results


def get_signatures_by_country(country_id):
    """
    Return all signatures targeting or originating in a given country.
    For command-mode, country_id matches the LEADER's country.
    For absorber-mode, country_id matches the absorbing country.
    """
    catalog = list_jawboning_signatures()
    results = []
    for direction in ('command', 'absorber'):
        for sig_id, sig_data in catalog.get(direction, {}).items():
            if sig_data.get('country_id') == country_id:
                results.append({'signature_id': sig_id, **sig_data})
    return results


def get_signatures_by_direction(direction):
    """
    Return all signatures for a given direction ('command' or 'absorber').
    """
    catalog = list_jawboning_signatures()
    return [
        {'signature_id': sig_id, **sig_data}
        for sig_id, sig_data in catalog.get(direction, {}).items()
    ]


def get_signature_count():
    """Quick count helper for diagnostics."""
    catalog = list_jawboning_signatures()
    return {
        'command':  len(catalog.get('command', {})),
        'absorber': len(catalog.get('absorber', {})),
        'total':    sum(len(d) for d in catalog.values()),
    }


# ============================================================================
# WRITE FUNCTION — for future Layer B auto-learning
# ============================================================================
#
# Reserved for the future auto-learning layer. When Black Swan's Axis 4
# (Novelty Catalog) discovers a recurring novel signature, it can write
# that signature directly into Redis without a code deploy.
# ============================================================================

def write_jawboning_signature(signature_id, signature_data):
    """
    Write a single signature to Redis (used by future auto-learning layer).
    Signature data should follow the canonical per-entry schema documented
    at the top of this file.

    Validates basic schema before writing. Returns True on success.
    """
    required_fields = [
        'leader_id', 'country_id', 'direction', 'target_sector',
        'target_key', 'trigger_keywords', 'pattern_basis', 'confidence',
    ]
    missing = [f for f in required_fields if f not in signature_data]
    if missing:
        print(f"[Jawboning Signatures] write rejected for {signature_id}: missing {missing}")
        return False

    if signature_data['direction'] not in ('command', 'absorber'):
        print(f"[Jawboning Signatures] write rejected for {signature_id}: bad direction")
        return False

    ttl_seconds = JAWBONING_CATALOG_TTL_HOURS * 3600
    return _redis_set(_catalog_redis_key_single(signature_id), signature_data, ttl_seconds)


# ============================================================================
# ENDPOINT REGISTRATION
# ============================================================================

def register_jawboning_signatures_endpoints(app):
    """
    Register the read-only catalog endpoints on the Flask app.

    Endpoints:
      GET /api/jawboning/signatures                  — full catalog (Redis-cached)
      GET /api/jawboning/signatures/<sig_id>         — single entry (Redis-cached)
      GET /api/jawboning/signatures?leader=trump     — filtered by leader
      GET /api/jawboning/signatures?country=india    — filtered by country
      GET /api/jawboning/signatures?direction=command — filtered by direction
      GET /api/jawboning/signatures/count            — quick diagnostic count
      POST /api/jawboning/signatures/hydrate         — manual re-hydration
    """
    from flask import request as flask_request, jsonify

    @app.route('/api/jawboning/signatures', methods=['GET', 'OPTIONS'])
    def api_jawboning_signatures_list():
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            # Filter parameters
            leader    = flask_request.args.get('leader')
            country   = flask_request.args.get('country')
            direction = flask_request.args.get('direction')

            if leader:
                return jsonify({
                    'success':  True,
                    'filter':   {'leader': leader},
                    'count':    None,  # filled below
                    'results':  get_signatures_by_leader(leader),
                })
            if country:
                return jsonify({
                    'success':  True,
                    'filter':   {'country': country},
                    'results':  get_signatures_by_country(country),
                })
            if direction:
                if direction not in ('command', 'absorber'):
                    return jsonify({
                        'success': False,
                        'error':   "direction must be 'command' or 'absorber'",
                    }), 400
                return jsonify({
                    'success':  True,
                    'filter':   {'direction': direction},
                    'results':  get_signatures_by_direction(direction),
                })

            # No filter — return full catalog
            return jsonify({
                'success':       True,
                'catalog':       list_jawboning_signatures(),
                'count':         get_signature_count(),
                'served_at':     datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   f'{type(e).__name__}: {str(e)[:200]}',
            }), 500

    @app.route('/api/jawboning/signatures/count', methods=['GET'])
    def api_jawboning_signatures_count():
        try:
            return jsonify({'success': True, 'count': get_signature_count()})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/jawboning/signatures/hydrate', methods=['POST', 'OPTIONS'])
    def api_jawboning_signatures_hydrate():
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            stats = hydrate_catalog_to_redis()
            print(f"[Jawboning Signatures] Manual hydration: {stats}")
            return jsonify({'success': True, 'hydration_stats': stats})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # NOTE: <sig_id> route registered LAST so it doesn't shadow /count or /hydrate
    @app.route('/api/jawboning/signatures/<sig_id>', methods=['GET', 'OPTIONS'])
    def api_jawboning_signature_single(sig_id):
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            sig = read_jawboning_signature(sig_id)
            if sig is None:
                return jsonify({
                    'success': False,
                    'error':   f'signature_id "{sig_id}" not found',
                }), 404
            return jsonify({
                'success':       True,
                'signature_id':  sig_id,
                'signature':     sig,
                'served_at':     datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    print("[Jawboning Signatures] ✅ Endpoints registered:")
    print("[Jawboning Signatures]   GET  /api/jawboning/signatures")
    print("[Jawboning Signatures]   GET  /api/jawboning/signatures/<sig_id>")
    print("[Jawboning Signatures]   GET  /api/jawboning/signatures/count")
    print("[Jawboning Signatures]   POST /api/jawboning/signatures/hydrate")


# ============================================================================
# AUTO-HYDRATE ON MODULE IMPORT
# ============================================================================
#
# As soon as this module is imported (which happens once at app startup in
# app.py), populate Redis with the static catalog. Cross-process safe:
# multiple workers writing the same key is fine — last-write-wins, identical
# payload.
# ============================================================================

try:
    _hydration_stats = hydrate_catalog_to_redis()
    print(f"[Jawboning Signatures] ✅ Auto-hydration on import: {_hydration_stats}")
except Exception as _e:
    print(f"[Jawboning Signatures] ⚠️ Auto-hydration failed: {_e}")
    print(f"[Jawboning Signatures]    Endpoints will fall back to static catalog.")
