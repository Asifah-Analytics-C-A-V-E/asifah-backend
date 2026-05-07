"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — CONVERGENCE REGISTRY
  v1.0.0 (May 3 2026)
═══════════════════════════════════════════════════════════════════════

Single source of truth for cross-axis / cross-regional convergence narratives.

A "convergence" is a compound risk that emerges only when two or more
otherwise-independent signals fire simultaneously. The textbook example:

  - Country has active humanitarian crisis (Lebanon: 1M displaced, food insecurity)
  - Global commodity is in pressure surge (wheat: Black Sea grain corridor stress)
  - Country has structural import dependency on that commodity (Lebanon: 80% Black Sea wheat)
    → CONVERGENCE: humanitarian crisis × commodity surge × import dependency

This module is consumed by TWO layers of the analytical stack:

LAYER 2 — me_regional_bluf.py (and equivalents for other regions later):
  - Enriches existing humanitarian/stability signals with convergence context
  - Adds compound-risk language to the long_text of the trigger signal
  - Sets the {convergence_id}_active boolean flag on the signal for Layer 1 to read

LAYER 1 — global_pressure_index.py:
  - Detects convergence flags on signals flowing through regional BLUFs
  - Emits a NEW high-priority Tier-1 narrative for the convergence itself
  - Cross-regional tagging gives it +30 boost in synthesis ordering

ADDING A NEW CONVERGENCE:
  1. Append a dict to CONVERGENCE_REGISTRY below
  2. Verify the trigger_signal_category exists in the relevant regional BLUF
  3. Verify the commodity exists in commodity_tracker.COMMODITY_TYPES
  4. Deploy ME backend (both BLUF + GPI live there) — that's it

REQUIRED FIELDS per convergence entry:
  id                       — unique snake_case identifier (also used as category)
  commodity                — must match commodity_tracker COMMODITY_TYPES key
  country                  — country name for display + matching
  trigger_signal_category  — category string Layer 2 watches for in BLUF
  trigger_region           — which regional BLUF carries the trigger ('me', 'asia', etc.)
  commodity_threshold      — min alert level: 'elevated', 'high', or 'surge'
  regions                  — list of regions for cross-regional Tier-1 boost
  priority                 — narrative priority (10-15 range)
  icon                     — emoji
  color                    — hex color
  headline_template        — supports {alert} placeholder for commodity status
  detail                   — static prose body
  facts                    — dict of structured anchors (display + audit)
  enrichment_text_template — Layer 2 long_text append (supports {alert}, {signals})

OPTIONAL FIELDS:
  trigger_signal_min_level — only fire if trigger signal is at this level or higher
  notes                    — analyst notes (not displayed)
"""

# ════════════════════════════════════════════════════════════════════
# THE REGISTRY
# ════════════════════════════════════════════════════════════════════

CONVERGENCE_REGISTRY = [
    {
        'id':                      'wheat_lebanon',
        'commodity':               'wheat',
        'country':                 'lebanon',
        'trigger_signal_category': 'humanitarian_lebanon',
        'trigger_region':          'me',
        'commodity_threshold':     'elevated',          # fires at elevated, high, or surge
        'regions':                 ['me', 'europe'],     # ME = Lebanon, Europe = Black Sea (UA/RU)
        'priority':                13,
        'icon':                    '\U0001f33e',         # 🌾
        'color':                   '#f59e0b',             # amber — economic axis primary
        'headline_template':       'Wheat-Lebanon convergence -- food security crisis compounded by global wheat {alert}',
        'detail': (
            'Lebanon imports ~60-67% of its wheat from Ukraine and ~80-90% combined '
            'from Black Sea (Ukraine + Russia). National wheat reserves stand at ~1 month '
            'since the 2020 Beirut port explosion destroyed national grain silos -- '
            'never rebuilt. 1.24M Lebanese projected to face acute food insecurity '
            '(IPC Phase 3+) through August 2026; Flash Appeal only 38% funded. '
            'Watch: Black Sea grain corridor status, Russian wheat export taxes, '
            'Lebanese Mills Association statements, Lebanese Pound bread-price index. '
            'Compound risk: any Black Sea disruption during active humanitarian crisis '
            'is materially worse than during peacetime.'
        ),
        'facts': {
            'import_dep_pct':  '60-67% Ukraine, 80-90% Black Sea',
            'reserve_months':  1,
            'reserve_note':    'silos destroyed in 2020 Beirut port explosion',
            'food_insecure':   '1.24M IPC Phase 3+ through Aug 2026',
            'appeal_funded':   '38%',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f WHEAT-LEBANON CONVERGENCE: Global wheat at {alert} '
            '({signals} signals). Lebanon imports ~60-67% of wheat from Ukraine and '
            '~80-90% combined Black Sea (UA+RU); national wheat reserves ~1 month '
            'since 2020 Beirut port explosion destroyed grain silos. Compound risk: '
            'any Black Sea grain corridor disruption is materially worse during active '
            'humanitarian crisis with 1.24M projected food-insecure (IPC Phase 3+).'
        ),
        'notes': (
            'Founding convergence -- shipped May 3, 2026. Lebanese wheat reserves '
            'have NOT been rebuilt since 2020 explosion; this is structural fragility.'
        ),
    },

    # ───────────────────────────────────────────────────────────────
    # ASIA CONVERGENCES (May 2026)
    # Cross-theater amplification narratives for the China-Taiwan-Japan
    # triangle, plus the China-Iran-Hormuz oil dependency vector.
    # Trigger region 'asia' or 'me' depending on origin signal.
    # ───────────────────────────────────────────────────────────────
    {
        'id':                      'pla_pressure_japan_response',
        'commodity':               None,                          # Not commodity-driven
        'country':                 'japan',
        'trigger_signal_category': 'japan_outbound_posture',
        'trigger_region':          'asia',
        'commodity_threshold':     None,                          # No commodity gate
        'regions':                 ['asia'],
        'priority':                14,
        'icon':                    '\U0001f396\ufe0f',             # 🎖️
        'color':                   '#ef4444',                       # red — security axis
        'headline_template':       'Asia security architecture activation -- China escalation + Japan posture hardening converge',
        'detail': (
            'Convergence pattern: China outbound rhetoric at L3+ (Directive or higher) '
            'AND Japan outbound posture at L3+ (PM/MoD/Diet committing to defense build-up '
            'or Article 9 reinterpretation language). When both fire simultaneously, '
            'this is the strongest available signal that East Asia security architecture '
            'is shifting from a bilateral US-Japan alliance frame to an explicit '
            'trilateral (US-Japan-Taiwan or US-Japan-Korea) posture. Watch for follow-on '
            'INDOPACOM signaling, Reciprocal Access Agreement updates, AUKUS Pillar 2 '
            'announcements, Japan-Philippines defense agreements. Compound risk: regional '
            'arms-race dynamics + reduced diplomatic off-ramp space.'
        ),
        'facts': {
            'china_threshold':    'outbound_max_level >= 3',
            'japan_threshold':    'outbound_max_level >= 3 OR article9_active',
            'historical_analog':  '2015 collective self-defense reinterpretation cycle',
            'key_indicators':     'JSDF deployment orders, INDOPACOM signaling, Diet votes',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f ASIA SECURITY ARCHITECTURE ACTIVATION: China outbound at {alert} '
            '({signals} signals) coincides with Japan posture hardening. This is the '
            'strongest convergence signal that regional alliance architecture is shifting '
            'toward explicit trilateral coordination. Watch INDOPACOM, RAA updates, AUKUS '
            'Pillar 2 expansion.'
        ),
        'notes': (
            'Asia-theatre founding convergence -- May 7 2026. Mirrors wheat-Lebanon '
            'pattern but for security rather than commodity axis.'
        ),
    },
    {
        'id':                      'taiwan_alliance_convergence',
        'commodity':               None,
        'country':                 'taiwan',
        'trigger_signal_category': 'taiwan_us_alliance',
        'trigger_region':          'asia',
        'commodity_threshold':     None,
        'regions':                 ['asia'],
        'priority':                14,
        'icon':                    '\U0001f91d',                    # 🤝
        'color':                   '#0ea5e9',                        # cyan — alliance axis
        'headline_template':       'Trilateral Taiwan defense convergence -- Japan + US + Taiwan signaling alignment',
        'detail': (
            'Convergence pattern: Japan taiwan_defense_active fingerprint TRUE + Taiwan '
            'us_alliance L3+ + (optionally) US INDOPACOM signaling at elevated levels. '
            'This converts what has historically been a strategically ambiguous '
            'US-Taiwan posture into an explicit trilateral defense commitment. '
            'Significantly raises the threshold for any PRC kinetic action against Taiwan '
            'and increases the probability of structured PLA escalation in response. '
            'Watch PLA Eastern Theater Command activity spikes, MFA condemnation cadence, '
            'TAO statements on "external interference."'
        ),
        'facts': {
            'japan_threshold':    'taiwan_defense_active = TRUE',
            'taiwan_threshold':   'us_alliance_level >= 3',
            'compound_effect':    'shift from strategic ambiguity to explicit trilateral commitment',
            'historical_analog':  '2021 Suga-Biden joint statement (Taiwan named for first time since 1969)',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f TRILATERAL TAIWAN DEFENSE CONVERGENCE: Japan committing to '
            'Taiwan defense + Taiwan signaling US alliance at {alert} ({signals} signals). '
            'Converts strategic ambiguity into explicit trilateral commitment. PLA '
            'escalation probability rises in response.'
        ),
        'notes': (
            'Captures the most consequential Asia convergence pattern -- '
            'Japan publicly defending Taiwan is a threshold change vs. all prior '
            'Japanese governments. Peter would have something to say about this.'
        ),
    },
    {
        'id':                      'hormuz_china_oil_dependency',
        'commodity':               'oil',
        'country':                 'china',
        'trigger_signal_category': 'iran_hormuz_pressure',
        'trigger_region':          'me',                            # Origin = Iran
        'commodity_threshold':     'elevated',                      # Lower bar than wheat-LBN
        'regions':                 ['me', 'asia'],                   # Cross-regional
        'priority':                15,                               # Highest -- structural China dependency
        'icon':                    '\U0001f6e2\ufe0f',                # 🛢️
        'color':                   '#f59e0b',                          # amber — economic axis
        'headline_template':       'China oil supply convergence -- Iran/Hormuz pressure compounded by China import dependency',
        'detail': (
            'China imports approximately 50% of its crude oil through the Strait of Hormuz. '
            'When Iran posture (theatre_score) reaches operational levels (L3+) or IRGC '
            'fingerprint shows Hormuz/Persian Gulf in named_targets, China faces direct '
            'pressure on its energy security. This explains why China consistently pushes '
            'de-escalation rhetoric in MFA briefings during Iran tensions, why China invests '
            'heavily in alternative supply (CPEC pipeline, BRI infrastructure, Russia-China '
            'oil pipelines, Central Asia gas), and why China has repeatedly mediated between '
            'Iran and Saudi Arabia. Compound risk: Hormuz disruption simultaneously with '
            'global oil pressure surge would force structural change to Chinese energy '
            'sourcing -- with cascading effects on Belt and Road, yuan settlement deals, '
            'and Sino-Iranian strategic partnership timelines.'
        ),
        'facts': {
            'china_oil_dep':       '~50% crude imports through Hormuz',
            'iran_threshold':      'theatre_score >= 60 OR irgc_level >= 3 OR hormuz in named_targets',
            'oil_threshold':       'elevated, high, or surge',
            'china_response':      'MFA de-escalation rhetoric, BRI/CPEC investment, RU/Central Asia substitution',
            'historical_analog':   '2019-2020 tanker-war period, 2024 Israel-Iran direct exchange',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f HORMUZ-CHINA OIL CONVERGENCE: Global oil at {alert} '
            '({signals} signals) AND Iran posture elevated. China imports ~50% of crude '
            'through Hormuz; Iran pressure on Hormuz directly stresses Chinese energy '
            'security. Watch China MFA "stability" framing, BRI/CPEC investment '
            'announcements, RU/Central Asia substitution moves, yuan settlement deal news.'
        ),
        'notes': (
            'First cross-regional Asia convergence (ME trigger -> Asia consumer). '
            'Mirrors wheat-Lebanon pattern (ME-trigger -> Europe-consumer). '
            'This is THE structural reason China cares so much about Iran. '
            'May 7 2026 -- Rachel + Peter contribution.'
        ),
    },

    # ───────────────────────────────────────────────────────────────
    # FUTURE CONVERGENCES — uncomment / adapt as new ones get identified.
    # Examples sketched below show how broad the pattern can stretch.
    # ───────────────────────────────────────────────────────────────
    # {
    #     'id':                      'wheat_egypt',
    #     'commodity':               'wheat',
    #     'country':                 'egypt',
    #     'trigger_signal_category': 'humanitarian_egypt',     # would need to exist
    #     'trigger_region':          'me',                       # or 'africa' if Egypt routed there
    #     'commodity_threshold':     'high',                     # higher bar for Egypt (more reserves)
    #     'regions':                 ['me', 'europe'],
    #     'priority':                12,
    #     'icon':                    '\U0001f33e',
    #     'color':                   '#f59e0b',
    #     ...
    # },
    # {
    #     'id':                      'oil_iraq',
    #     'commodity':               'oil',
    #     'country':                 'iraq',
    #     'trigger_signal_category': 'iraq_pipeline_disruption',
    #     'trigger_region':          'me',
    #     'commodity_threshold':     'high',
    #     'regions':                 ['me'],
    #     ...
    # },
    # {
    #     'id':                      'cobalt_drc',
    #     'commodity':               'cobalt',
    #     'country':                 'drc',
    #     'trigger_signal_category': 'drc_conflict_kivu',
    #     'trigger_region':          'wha',                      # or 'africa' once routed
    #     'commodity_threshold':     'elevated',
    #     'regions':                 ['wha', 'asia'],            # DRC = source, China = consumer
    #     ...
    # },
]


# ════════════════════════════════════════════════════════════════════
# HELPERS — used by both Layer 1 (GPI) and Layer 2 (ME BLUF)
# ════════════════════════════════════════════════════════════════════

# Threshold ordering — higher index = more severe alert
_ALERT_ORDER = ['normal', 'elevated', 'high', 'surge']


def alert_meets_threshold(actual_alert, threshold):
    """
    Return True if the actual commodity alert level is at or above the
    configured threshold for this convergence.

    Examples:
        alert_meets_threshold('surge', 'elevated')   -> True
        alert_meets_threshold('elevated', 'surge')   -> False
        alert_meets_threshold('normal', 'elevated')  -> False
    """
    try:
        return _ALERT_ORDER.index(actual_alert) >= _ALERT_ORDER.index(threshold)
    except ValueError:
        return False


def find_convergence_by_country_commodity(country, commodity):
    """
    Layer 2 helper: when ME BLUF builds a country signal (e.g. lebanon humanitarian),
    look up whether any registered convergence applies to this country+commodity pair.

    Returns the registry dict if found, None otherwise.
    """
    for entry in CONVERGENCE_REGISTRY:
        if entry['country'] == country and entry['commodity'] == commodity:
            return entry
    return None


def find_convergences_for_country(country):
    """
    Layer 2 helper: list ALL convergences registered for a country.
    A country may have multiple convergence entries (e.g. wheat AND oil).

    Returns a list of registry dicts (possibly empty).
    """
    return [e for e in CONVERGENCE_REGISTRY if e['country'] == country]


def find_convergence_by_trigger(category, region):
    """
    Layer 1 helper: GPI sees a signal flowing from a regional BLUF and asks
    'is this signal a convergence trigger for any registered convergence?'

    Returns the registry dict if found, None otherwise.
    """
    for entry in CONVERGENCE_REGISTRY:
        if (entry['trigger_signal_category'] == category
            and entry['trigger_region'] == region):
            return entry
    return None


def format_headline(entry, alert_level):
    """Format the headline_template with the actual alert level."""
    return entry['headline_template'].format(alert=alert_level.upper())


def format_enrichment_text(entry, alert_level, signal_count):
    """Format the Layer 2 enrichment text template."""
    return entry['enrichment_text_template'].format(
        alert=alert_level.upper(),
        signals=signal_count,
    )
