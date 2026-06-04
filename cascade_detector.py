"""
cascade_detector.py
Asifah Analytics -- ME Backend Module
v1.0.0 -- May 17, 2026

GLOBAL CASCADE COMMODITY DETECTOR

Solves the "hidden chokepoint" problem in commodity markets:
when one upstream disruption (e.g., Strait of Hormuz closure) propagates
through a hidden intermediate input (e.g., sulfur/sulfuric acid) into
MANY downstream commodity sectors that look superficially unrelated
(copper, nickel, fertilizer, batteries, semiconductors), no single
sector signal is dramatic on its own -- the PATTERN of multiple
sectors signaling stress through the same hidden chokepoint is what
matters analytically.

ARCHITECTURE:
  Registry-driven cascade chain detection. Each chain is a structured
  mapping of `chokepoint -> intermediate -> [downstream commodities]`.
  Detector scans:
    1. Chokepoint signals (from existing rhetoric trackers + commodity tracker)
    2. Intermediate commodity stress (price + supply signals)
    3. Downstream commodity signals (from cascade_via metadata in commodity_tracker)
  Emits a BLUF-shaped payload at /api/cascade-convergence/bluf
  that GPI consumes as a 6th regional BLUF feeding the ECONOMIC axis.

CASCADE CHAINS (v1.0 registry):
  1. HORMUZ_SULFUR_CASCADE
     chokepoint:    strait_of_hormuz
     intermediate:  sulfur / sulfuric acid
     downstream:    copper, nickel, potash, lithium, cobalt, semiconductors
     status:        ACTIVE since Feb 28 2026 (Hormuz closed + China sulfur
                    export ban + Turkey ban + India considering)

  Future chains (placeholder for v1.1+):
  2. TUNGSTEN_MILITARY_CASCADE (China export controls -> military electronics)
  3. HELIUM_SEMICONDUCTOR_CASCADE (Qatar + Russia + US -> semiconductors)
  4. SUEZ_WHEAT_CASCADE (Black Sea grain corridor -> global food)

CONVERGENCE TIERS:
  0 chains active                  -> BASELINE
  1 chain partially active         -> WATCH        (L2)
  1 chain fully active             -> ACTIVE       (L4)
  2+ chains simultaneously active  -> COMPOUND     (L5)

Author: RCGG / Asifah Analytics
"""
from datetime import datetime, timezone
import json
import os
import re

# ============================================================
# CASCADE CHAIN REGISTRY
# ============================================================
# Each chain documents: upstream chokepoint, intermediate commodity,
# downstream commodities, detection patterns, and severity signals.
# Add new chains here; detector logic generalizes automatically.

CASCADE_CHAINS = {
    'hormuz_sulfur_cascade': {
        'label':         'Hormuz Sulfur Cascade',
        'icon':          '⚗️',
        'description':   (
            'Strait of Hormuz closure traps Gulf sulfur exports (~45% of global '
            'trade). Sulfuric acid scarcity propagates into copper processing '
            '(Chile #1 vulnerable), nickel HPAL (Indonesia), phosphate fertilizers '
            '(global food security), plus lithium/cobalt refining and semiconductor '
            'wafer cleaning. China + Turkey sulfur export bans amplify. '
            'Source: Reuters/Andy Home Apr 17 2026; S&P Global Mar 17 2026; FP Apr 17 2026.'
        ),
        'chokepoint': {
            'key':           'strait_of_hormuz',
            'label':         'Strait of Hormuz',
            'flag':          '🇮🇷',
            # Keywords that indicate the chokepoint is constrained
            'active_keywords': [
                'strait of hormuz closed', 'hormuz closure', 'hormuz blockade',
                'hormuz shut', 'hormuz traffic restricted', 'hormuz transit halted',
                'iranian mining hormuz', 'hormuz mining', 'gulf shipping disrupted',
                'persian gulf shipping halt', 'gulf tanker traffic',
            ],
        },
        'intermediate': {
            'key':           'sulfur',
            'label':         'Sulfur / Sulfuric Acid',
            'icon':          '⚗️',
            'stress_keywords': [
                'sulfur shortage', 'sulfuric acid shortage',
                'sulfur export ban', 'sulfur prices surge',
                'sulfuric acid prices rise', 'china sulfur export ban',
                'turkey sulfur ban', 'india sulfur export',
                'sulfur trapped', 'gulf sulfur exports',
                'sulfur cascade', 'sulfuric acid crunch',
                'sulfur supply shock', 'sulfur scarcity',
            ],
            'high_intensity_markers': [
                'china sulfur export ban', 'sulfur prices double',
                'copper oxide operations close', 'hpal production cut',
            ],
        },
        'downstream_commodities': [
            'copper', 'nickel', 'potash', 'lithium', 'cobalt', 'semiconductors',
        ],
        'downstream_signal_keywords': {
            # Country + commodity stress markers per downstream sector
            'copper': [
                'chile copper sulfuric acid', 'codelco acid supply',
                'copper oxide processing risk', 'copper smelter acid shortage',
                'antofagasta acid supply', 'ivanhoe mines acid warning',
            ],
            'nickel': [
                'indonesia nickel sulfur', 'hpal sulfur shortage',
                'nickel sulfate price surge', 'battery grade nickel risk',
                'indonesian hpal acid', 'tsingshan nickel sulfur',
                'weda bay sulfur', 'bahodopi sulfur',
            ],
            'potash': [
                'fertilizer shortage', 'phosphate fertilizer crunch',
                'phosphate prices surge', 'ammonium sulfate shortage',
                'planting season fertilizer crisis', 'urea cost surge',
            ],
            'lithium': [
                'lithium refining acid', 'cathode active material cost',
                'china lithium refining cost', 'lithium sulfate shortage',
            ],
            'cobalt': [
                'cobalt refining acid', 'cobalt sulfate cost surge',
                'drc cobalt acid supply',
            ],
            'semiconductors': [
                'semiconductor wafer acid', 'chip fab sulfuric acid',
                'tsmc acid supply', 'samsung wafer acid',
            ],
        },
        # Tier escalation: how many downstream commodities need to fire
        'downstream_threshold_watch':   1,  # 1 downstream firing = WATCH
        'downstream_threshold_active':  3,  # 3 downstream firing = ACTIVE
        'downstream_threshold_compound':5,  # 5+ downstream firing = COMPOUND
        # Strategic memo for so-what generation
        'so_what': (
            'When Hormuz closure is paired with sulfur stress + 3 downstream signals, '
            'the cascade is operational. This is the Andy Home Reuters thesis: '
            'the Iran war is rippling through copper + nickel + fertilizer via a '
            'commodity (sulfur) most analysts dont track. Chile is structurally '
            'amplified-exposed (copper #1 + sulfur consumer). Indonesia nickel is '
            'next. Africa faces 90% sulfur-import dependency. If sustained >3 weeks, '
            'copper oxide operations face shutdown (Ivanhoe Mines founder warning).'
        ),
        # Country amplification: who is structurally exposed
        'amplified_countries': {
            'chile':      {'commodity': 'copper',  'rank': 1, 'reason': '20% copper processing uses imported sulfuric acid; China primary supplier now banning'},
            'indonesia':  {'commodity': 'nickel',  'rank': 1, 'reason': 'World #1 nickel; HPAL chemistry requires substantial sulfuric acid; 80% price surge already'},
            'morocco':    {'commodity': 'potash',  'rank': 3, 'reason': 'Phosphate processing requires sulfuric acid; OCP largest globally'},
            'africa':     {'commodity': 'multi',   'rank': 1, 'reason': '90% of African sulfur imports come from Middle East; mining-sector wide exposure'},
        },
    },
    # ============================================================
    # FERTILIZER -> FOOD SECURITY CASCADE  (Stage 2a — June 2026)
    # ============================================================
    # Coco's thesis: Hormuz closure traps Gulf sulfur/fertilizer feedstock ->
    # fertilizer scarcity hits BEFORE spring planting -> reduced yields ->
    # food price rise -> food-access crisis (Global South first). This is the
    # PRESENT-STATE chain; the seasonal time-lag layer (planting/harvest windows)
    # arrives in Stage 2b. Convergence framing only — we report that the setup
    # is present, NOT that a food crisis is predicted.
    'fertilizer_food_security_cascade': {
        'label':         'Fertilizer → Food Security Cascade',
        'icon':          '🌾',
        'description':   (
            'Strait of Hormuz closure traps Gulf sulfur/fertilizer feedstock, '
            'driving potash/phosphate/urea scarcity. Fertilizer disruption ahead '
            'of the planting window propagates into staple-crop yields (wheat, '
            'maize, rice) and edible oils, surfacing as FAO Food Price Index rises '
            'and IPC food-access stress — Global South import-dependent states most '
            'exposed. CONVERGENCE indicator: reports that the fertilizer→food setup '
            'is present, not that a food crisis is predicted.'
        ),
        'chokepoint': {
            'key':           'strait_of_hormuz',
            'label':         'Strait of Hormuz',
            'flag':          '🇮🇷',
            'active_keywords': [
                'strait of hormuz closed', 'hormuz closure', 'hormuz blockade',
                'hormuz shut', 'hormuz traffic restricted', 'hormuz transit halted',
                'iranian mining hormuz', 'hormuz mining', 'gulf shipping disrupted',
                'persian gulf shipping halt', 'gulf tanker traffic',
            ],
        },
        'intermediate': {
            'key':           'fertilizer',
            'label':         'Fertilizer (Potash / Phosphate / Urea / Ammonia)',
            'icon':          '🧪',
            'stress_keywords': [
                'fertilizer shortage', 'fertilizer prices surge', 'fertilizer export ban',
                'potash shortage', 'potash prices surge', 'phosphate fertilizer crunch',
                'phosphate prices surge', 'urea cost surge', 'urea prices rise',
                'ammonia shortage', 'ammonium sulfate shortage', 'nitrogen fertilizer shortage',
                'fertilizer affordability', 'fertilizer rationing', 'DAP prices surge',
                'MOP fertilizer', 'planting season fertilizer crisis', 'fertilizer supply shock',
            ],
            'high_intensity_markers': [
                'fertilizer export ban', 'planting season fertilizer crisis',
                'farmers cannot afford fertilizer', 'fertilizer rationing',
                'fertilizer prices double',
            ],
        },
        'downstream_commodities': [
            'wheat', 'maize', 'rice', 'vegetable_oils', 'food_security',
        ],
        'downstream_signal_keywords': {
            'wheat': [
                'wheat prices rise', 'wheat shortage', 'wheat export ban',
                'global wheat supply', 'wheat yield decline', 'wheat crop forecast cut',
            ],
            'maize': [
                'maize prices surge', 'corn prices surge', 'maize shortage',
                'corn yield decline', 'maize crop forecast',
            ],
            'rice': [
                'rice prices surge', 'rice export ban', 'rice shortage',
                'rice crop forecast cut',
            ],
            'vegetable_oils': [
                'vegetable oil prices rise', 'palm oil prices surge', 'edible oil shortage',
                'soybean oil prices', 'sunflower oil shortage',
            ],
            'food_security': [
                'food price index rise', 'ffpi rise', 'food inflation',
                'food insecurity', 'ipc phase', 'famine', 'food access crisis',
                'global food crisis', 'hunger crisis', 'food import dependency',
                'staple food shortage',
            ],
        },
        # Food has 5 downstream sectors; compound at 4 (allows one to lag)
        'downstream_threshold_watch':    1,
        'downstream_threshold_active':   3,
        'downstream_threshold_compound': 4,
        'so_what': (
            'When Hormuz closure is paired with fertilizer stress plus staple-crop '
            'and food-security signals, the fertilizer→food cascade is operational. '
            'Fertilizer applied (or withheld) during the planting window does not '
            'show up in food prices until the harvest months later — so a quiet FFPI '
            'today does not mean the setup is benign. Import-dependent Global South '
            'states (Egypt, Nigeria, Bangladesh, Yemen, sub-Saharan Africa) absorb '
            'the shock first; buffered producers (US, EU) absorb it last. The Stage 2b '
            'time-lag layer makes this planting→harvest delay explicit.'
        ),
        'amplified_countries': {
            'egypt':       {'commodity': 'wheat',         'rank': 1, 'reason': "World's largest wheat importer; bread subsidy system structurally exposed to wheat price + supply shocks"},
            'nigeria':     {'commodity': 'food_security', 'rank': 1, 'reason': 'High food-import dependency + domestic fertilizer-access constraints; large population at IPC stress margin'},
            'india':       {'commodity': 'fertilizer',    'rank': 1, 'reason': "Massive fertilizer importer + subsidizer; planting-season fertilizer availability directly drives kharif/rabi yields"},
            'bangladesh':  {'commodity': 'rice',          'rank': 2, 'reason': 'Dense population + rice-staple dependency + fertilizer-import reliance; thin buffer against yield shortfalls'},
            'yemen':       {'commodity': 'food_security', 'rank': 1, 'reason': 'Already acute IPC food insecurity; near-total food-import dependency amplifies any global price shock'},
            'africa':      {'commodity': 'multi',         'rank': 1, 'reason': 'Broad fertilizer-import + food-import dependency across sub-Saharan states; lowest buffer capacity globally'},
        },
    },
    # ============================================================
    # Future cascade chains (placeholders for v1.1+)
    # ============================================================
    # 'tungsten_military_cascade': { ... },
    # 'helium_semiconductor_cascade': { ... },
    # 'suez_wheat_cascade': { ... },
}


# ============================================================
# SEVERITY SCORING
# ============================================================
SEVERITY_BASELINE = 1
SEVERITY_MEDIUM   = 2
SEVERITY_HIGH     = 3


# ============================================================
# DETECTION FUNCTIONS
# ============================================================
def _scan_text_for_keywords(text, keywords):
    """
    Scan text against a keyword list. Returns (matched_count, matched_keywords).
    """
    if not text or not keywords:
        return (0, [])
    text_lower = text.lower()
    matches = [kw for kw in keywords if kw in text_lower]
    return (len(matches), matches)


def _detect_chokepoint_status(chain_cfg, articles):
    """
    Scan articles for chokepoint-active signals.
    Returns dict: {active: bool, signal_count: int, matched_keywords: list, top_article: dict|None}
    """
    chokepoint = chain_cfg.get('chokepoint', {})
    keywords = chokepoint.get('active_keywords', [])
    if not keywords or not articles:
        return {'active': False, 'signal_count': 0, 'matched_keywords': [], 'top_article': None}

    total_matches = 0
    all_matched = []
    top_article = None
    for art in articles:
        title = (art.get('title') or '').lower()
        desc  = (art.get('description') or art.get('snippet') or '').lower()
        text = f"{title} {desc}"
        n, matched = _scan_text_for_keywords(text, keywords)
        if n > 0:
            total_matches += n
            all_matched.extend(matched)
            if top_article is None:
                top_article = art

    # Active if 1+ articles mention chokepoint constraint
    return {
        'active':           total_matches > 0,
        'signal_count':     total_matches,
        'matched_keywords': list(set(all_matched))[:5],
        'top_article':      top_article,
    }


def _detect_intermediate_stress(chain_cfg, articles):
    """
    Scan articles for intermediate-commodity stress signals (e.g., sulfur).
    Returns dict: {active: bool, severity: 1-3, signal_count: int, matched_keywords: list}
    """
    intermediate = chain_cfg.get('intermediate', {})
    keywords = intermediate.get('stress_keywords', [])
    high_markers = intermediate.get('high_intensity_markers', [])
    if not keywords or not articles:
        return {'active': False, 'severity': 0, 'signal_count': 0, 'matched_keywords': []}

    total_matches = 0
    all_matched = []
    high_intensity = False
    for art in articles:
        title = (art.get('title') or '').lower()
        desc  = (art.get('description') or art.get('snippet') or '').lower()
        text = f"{title} {desc}"
        n, matched = _scan_text_for_keywords(text, keywords)
        if n > 0:
            total_matches += n
            all_matched.extend(matched)
        # Check high-intensity markers
        if any(m in text for m in high_markers):
            high_intensity = True

    if total_matches == 0:
        return {'active': False, 'severity': 0, 'signal_count': 0, 'matched_keywords': []}

    severity = SEVERITY_HIGH if high_intensity else (SEVERITY_MEDIUM if total_matches >= 3 else SEVERITY_BASELINE)

    return {
        'active':           True,
        'severity':         severity,
        'signal_count':     total_matches,
        'matched_keywords': list(set(all_matched))[:5],
    }


def _detect_downstream_signals(chain_cfg, articles):
    """
    Scan articles for downstream commodity stress per cascade chain.
    Returns dict: {commodity: {active, signal_count, matched_keywords}}
    """
    downstream_kw_map = chain_cfg.get('downstream_signal_keywords', {})
    if not downstream_kw_map or not articles:
        return {}

    results = {}
    for commodity, keywords in downstream_kw_map.items():
        total_matches = 0
        all_matched = []
        for art in articles:
            title = (art.get('title') or '').lower()
            desc  = (art.get('description') or art.get('snippet') or '').lower()
            text = f"{title} {desc}"
            n, matched = _scan_text_for_keywords(text, keywords)
            if n > 0:
                total_matches += n
                all_matched.extend(matched)
        if total_matches > 0:
            results[commodity] = {
                'active':           True,
                'signal_count':     total_matches,
                'matched_keywords': list(set(all_matched))[:3],
            }
    return results


def detect_cascade(chain_key, chain_cfg, articles):
    """
    Run full cascade detection for a single chain.
    Returns dict with chokepoint, intermediate, downstream results + tier.
    """
    chokepoint_result   = _detect_chokepoint_status(chain_cfg, articles)
    intermediate_result = _detect_intermediate_stress(chain_cfg, articles)
    downstream_result   = _detect_downstream_signals(chain_cfg, articles)

    downstream_active_count = len(downstream_result)

    # Tier escalation logic
    chokepoint_active   = chokepoint_result['active']
    intermediate_active = intermediate_result['active']
    threshold_watch   = chain_cfg.get('downstream_threshold_watch', 1)
    threshold_active  = chain_cfg.get('downstream_threshold_active', 3)
    threshold_compound = chain_cfg.get('downstream_threshold_compound', 5)

    if (chokepoint_active and intermediate_active
            and downstream_active_count >= threshold_compound):
        tier = 'compound'
        level = 5
        tier_label = 'COMPOUND CASCADE'
    elif chokepoint_active and intermediate_active and downstream_active_count >= threshold_active:
        tier = 'active'
        level = 4
        tier_label = 'CASCADE ACTIVE'
    elif intermediate_active or (chokepoint_active and downstream_active_count >= threshold_watch):
        tier = 'watch'
        level = 2
        tier_label = 'CASCADE WATCH'
    elif chokepoint_active or intermediate_active or downstream_active_count > 0:
        tier = 'monitoring'
        level = 1
        tier_label = 'MONITORING'
    else:
        tier = 'baseline'
        level = 0
        tier_label = 'BASELINE'

    return {
        'chain_key':       chain_key,
        'chain_label':     chain_cfg.get('label', chain_key),
        'icon':            chain_cfg.get('icon', '⚗️'),
        'description':     chain_cfg.get('description', ''),
        'chokepoint':      chokepoint_result,
        'intermediate':    intermediate_result,
        'downstream':      downstream_result,
        'downstream_active_count': downstream_active_count,
        'tier':            tier,
        'tier_label':      tier_label,
        'level':           level,
        'so_what':         chain_cfg.get('so_what', '') if level >= 2 else '',
        'amplified_countries': chain_cfg.get('amplified_countries', {}) if level >= 2 else {},
    }


def detect_all_cascades(articles):
    """
    Run cascade detection across all registered chains.
    Returns list of cascade-detection results.
    """
    results = []
    for chain_key, chain_cfg in CASCADE_CHAINS.items():
        result = detect_cascade(chain_key, chain_cfg, articles or [])
        results.append(result)
    return results


# ============================================================
# AGGREGATION
# ============================================================
def aggregate_cascade_convergence(cascade_results):
    """
    Aggregate cascade results into overall convergence assessment.
    Returns dict with global tier + level + countries-at-risk.
    """
    if not cascade_results:
        return {
            'tier':                'baseline',
            'max_level':           0,
            'level_label':         'BASELINE -- No cascade chains active',
            'chains_active':       0,
            'chains_at_watch':     0,
            'chains_active_list':  [],
            'amplified_countries': [],
            'downstream_commodities_stressed': [],
        }

    # Count chain states
    active_chains   = [r for r in cascade_results if r['tier'] in ('active', 'compound')]
    watch_chains    = [r for r in cascade_results if r['tier'] == 'watch']
    monitoring_chains = [r for r in cascade_results if r['tier'] == 'monitoring']

    chains_active_count   = len(active_chains)
    chains_at_watch_count = len(watch_chains)

    # Collect amplified countries across active chains
    amplified = {}
    for r in active_chains:
        for country, info in r.get('amplified_countries', {}).items():
            amplified.setdefault(country, []).append({
                'chain': r['chain_label'],
                'commodity': info.get('commodity', '?'),
                'rank': info.get('rank', '?'),
                'reason': info.get('reason', ''),
            })

    # Collect all downstream commodities stressed
    downstream_commodities = set()
    for r in cascade_results:
        for commodity in r.get('downstream', {}).keys():
            downstream_commodities.add(commodity)

    # Determine global cascade tier
    if chains_active_count >= 2:
        tier = 'compound'
        max_level = 5
        label = f'COMPOUND CASCADE -- {chains_active_count} chains simultaneously active'
    elif chains_active_count >= 1:
        tier = 'active'
        max_level = 4
        chain_names = [r['chain_label'] for r in active_chains]
        label = f'CASCADE ACTIVE -- {", ".join(chain_names)}'
    elif chains_at_watch_count >= 1:
        tier = 'watch'
        max_level = 2
        chain_names = [r['chain_label'] for r in watch_chains]
        label = f'CASCADE WATCH -- {", ".join(chain_names)}'
    elif len(monitoring_chains) > 0:
        tier = 'monitoring'
        max_level = 1
        label = f'MONITORING -- {len(monitoring_chains)} chain(s) showing partial signals'
    else:
        tier = 'baseline'
        max_level = 0
        label = 'BASELINE -- no cascade chains active'

    return {
        'tier':                tier,
        'max_level':           max_level,
        'level_label':         label,
        'chains_active':       chains_active_count,
        'chains_at_watch':     chains_at_watch_count,
        'chains_active_list':  [r['chain_label'] for r in active_chains],
        'amplified_countries': amplified,
        'downstream_commodities_stressed': sorted(downstream_commodities),
    }


# ============================================================
# BLUF-SHAPED PAYLOAD BUILDER (consumed by GPI)
# ============================================================
def build_cascade_bluf(cascade_results, aggregation=None):
    """
    Build BLUF-shaped payload that GPI consumes via REGIONAL_BLUF_ENDPOINTS.
    Mirrors humanitarian_convergence_detector pattern: pseudo-region with
    pressure_type='economic' so GPI's classifier routes signals into the
    economic axis.
    """
    if aggregation is None:
        aggregation = aggregate_cascade_convergence(cascade_results or [])

    tier = aggregation['tier']
    max_level = aggregation['max_level']
    posture_label = aggregation['level_label']

    # Color per tier (matches canonical GPI scheme)
    posture_color = {
        'baseline':   '#6b7280',
        'monitoring': '#94a3b8',
        'watch':      '#f59e0b',
        'active':     '#f97316',
        'compound':   '#dc2626',
    }.get(tier, '#6b7280')

    # Build canonical signal payload per chain
    canonical_signals = []
    for r in (cascade_results or []):
        if r['level'] < 2:
            continue  # only surface watch+ tier signals

        # Build short + long text
        chain_label = r['chain_label']
        tier_label = r['tier_label']
        downstream_count = r['downstream_active_count']
        ds_names = list(r.get('downstream', {}).keys())

        short_text = (
            f"{r['icon']} {tier_label}: {chain_label} -- "
            f"{downstream_count}/{len(r.get('downstream', {}) or [{}])} downstream sectors stressed"
        )[:150]

        long_text_parts = [r.get('description', '')]
        if r.get('chokepoint', {}).get('active'):
            cp_kws = r['chokepoint'].get('matched_keywords', [])
            long_text_parts.append(
                f"CHOKEPOINT ACTIVE: {', '.join(cp_kws[:3]) if cp_kws else 'detected'}."
            )
        if r.get('intermediate', {}).get('active'):
            im_kws = r['intermediate'].get('matched_keywords', [])
            long_text_parts.append(
                f"INTERMEDIATE STRESS: {', '.join(im_kws[:3]) if im_kws else 'detected'} "
                f"(severity {r['intermediate'].get('severity', '?')}/3)."
            )
        if ds_names:
            long_text_parts.append(
                f"DOWNSTREAM IMPACT: {', '.join(ds_names)}."
            )
        if r.get('so_what'):
            long_text_parts.append(f"SO WHAT: {r['so_what']}")

        long_text = ' '.join(long_text_parts)

        canonical_signals.append({
            'category':      f"cascade_{r['chain_key']}",
            'chain':         r['chain_key'],
            'theatre':       'global_cascade',
            'region':        'global_cascade',
            'level':         r['level'],
            'pressure_type': 'economic',   # routes into GPI economic axis
            'icon':          r['icon'],
            'color':         posture_color,
            'short_text':    short_text,
            'long_text':     long_text,
            'priority':      r['level'] * 3,
            'amplified_countries': r.get('amplified_countries', {}),
            'downstream_stressed': ds_names,
        })

    # Sort by level desc
    canonical_signals.sort(key=lambda s: -s['level'])

    return {
        'region':         'global_cascade',
        'max_level':      max_level,
        'peak_level':     max_level,
        'posture_label':  posture_label,
        'posture_color':  posture_color,
        'top_signals':    canonical_signals[:5],
        'signals':        canonical_signals,
        'updated_at':     datetime.now(timezone.utc).isoformat(),
        'meta': {
            'tier':                tier,
            'chains_active':       aggregation['chains_active'],
            'chains_at_watch':     aggregation['chains_at_watch'],
            'chains_active_list':  aggregation['chains_active_list'],
            'amplified_countries': aggregation['amplified_countries'],
            'downstream_commodities_stressed': aggregation['downstream_commodities_stressed'],
            'detector_version':    'cascade_detector v1.0.0',
            'chains_registered':   list(CASCADE_CHAINS.keys()),
        },
    }


def detect_and_build_bluf(articles):
    """
    Top-level convenience: detect all cascades + aggregate + build BLUF.
    """
    cascade_results = detect_all_cascades(articles or [])
    aggregation = aggregate_cascade_convergence(cascade_results)
    return build_cascade_bluf(cascade_results, aggregation)


# ============================================================
# FLASK ROUTE REGISTRATION
# ============================================================
def register_cascade_detector_routes(app, redis_client=None, json_module=None):
    """
    Register cascade detector endpoints on the Flask app.

    v1.1.0 (May 19 2026) — REDIS PATTERN FIX
    Previous version expected redis-py client object (r.get/r.setex method
    interface). Asifah platform uses Upstash REST API directly across all
    rhetoric trackers + GPI + butterfly_reader. This created an architectural
    mismatch where the detector silently returned zero articles regardless
    of whether trackers had cached data.

    Fix: use the same Upstash REST pattern as rhetoric_tracker_iran.py and
    siblings. No app.py changes required.

    Args:
      app:           Flask app instance.
      redis_client:  (Legacy parameter — no longer used; kept for backward compat)
      json_module:   Optional json module reference.

    Endpoints registered:
      GET /api/cascade-convergence/bluf
          BLUF-shaped payload consumed by GPI as 6th regional BLUF
          (feeding the economic axis).
      GET /api/cascade-convergence/details
          Full chain-by-chain detection details + amplified country breakdown.
      GET /api/cascade-convergence/health
          Health check.
    """
    from flask import jsonify

    _json = json_module if json_module else __import__('json')

    # Pull Upstash credentials from environment (canonical Asifah pattern)
    UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
    UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

    def _upstash_get(key):
        """
        Direct Upstash REST GET — mirrors the pattern used by every other
        Asifah module. Returns parsed JSON, raw string, or None on failure.
        """
        if not UPSTASH_URL or not UPSTASH_TOKEN:
            return None
        import requests as _requests
        try:
            resp = _requests.get(
                f"{UPSTASH_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                timeout=5,
            )
            if not resp.ok:
                return None
            data = resp.json()
            raw = data.get('result')
            if raw is None:
                return None
            try:
                return _json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                return raw
        except Exception as e:
            print(f'[cascade_detector] Upstash GET error ({key}): {str(e)[:80]}')
            return None

    def _upstash_setex(key, ttl, value):
        """Direct Upstash REST SET with EX param — mirrors canonical pattern."""
        if not UPSTASH_URL or not UPSTASH_TOKEN:
            return False
        import requests as _requests
        try:
            payload = _json.dumps(value, default=str) if not isinstance(value, str) else value
            resp = _requests.post(
                f"{UPSTASH_URL}/set/{key}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_TOKEN}",
                    "Content-Type":  "application/json",
                },
                data=payload,
                params={"EX": ttl} if ttl else {},
                timeout=5,
            )
            return resp.json().get('result') == 'OK'
        except Exception as e:
            print(f'[cascade_detector] Upstash SET error ({key}): {str(e)[:80]}')
            return False

    def _gather_articles():
        """
        Pull article pools from cached ME rhetoric trackers via Upstash REST.

        Strategy: each rhetoric tracker stores its latest scan at
        rhetoric:<country>:latest in Redis. Each scan has actors[X].top_articles.
        We dedupe by URL to avoid counting the same article multiple times
        across actors.
        """
        articles = []
        seen_urls = set()

        # ME rhetoric tracker cache keys (canonical naming — confirmed against
        # rhetoric_tracker_iran.py line 103: RHETORIC_CACHE_KEY='rhetoric:iran:latest')
        rhetoric_keys = [
            'rhetoric:iran:latest',
            'rhetoric:israel:latest',
            'rhetoric:lebanon:latest',
            'rhetoric:syria:latest',
            'rhetoric:yemen:latest',
            'rhetoric:iraq:latest',
            'rhetoric:oman:latest',
        ]

        for key in rhetoric_keys:
            try:
                cached = _upstash_get(key)
                if not isinstance(cached, dict):
                    continue

                actors = cached.get('actors', {}) or {}
                if not isinstance(actors, dict):
                    continue

                for actor_data in actors.values():
                    if not isinstance(actor_data, dict):
                        continue
                    for art in (actor_data.get('top_articles', []) or []):
                        if not isinstance(art, dict):
                            continue
                        url = art.get('url') or art.get('link') or ''
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        articles.append(art)
            except Exception as e:
                print(f'[cascade_detector] Skipping {key}: {str(e)[:80]}')
                continue

        print(f'[cascade_detector] Gathered {len(articles)} articles from {len(rhetoric_keys)} tracker caches')
        return articles

    # ────────────────────────────────────────────────────────────
    # GET /api/cascade-convergence/bluf
    # ────────────────────────────────────────────────────────────
    @app.route('/api/cascade-convergence/bluf', methods=['GET'])
    def cascade_convergence_bluf():
        """
        BLUF-shaped payload consumed by GPI.
        Detects chokepoint -> intermediate -> downstream cascades and emits
        them as economic-axis signals.

        Query param: ?force=true bypasses 30-min cache.
        """
        from flask import request
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        try:
            # Try cached BLUF first (30-min TTL) — unless force=true
            if not force:
                cached = _upstash_get('cascade_convergence:bluf:latest')
                if cached and isinstance(cached, dict):
                    return jsonify(cached), 200

            # Build fresh
            articles = _gather_articles()
            bluf = detect_and_build_bluf(articles)

            # Cache for 30 min
            _upstash_setex('cascade_convergence:bluf:latest', 1800, bluf)

            return jsonify(bluf), 200

        except Exception as e:
            print(f'[cascade_detector] error: {e}')
            return jsonify({
                'region':        'global_cascade',
                'max_level':     0,
                'peak_level':    0,
                'posture_label': 'OFFLINE -- detector error',
                'posture_color': '#6b7280',
                'top_signals':   [],
                'signals':       [],
                'updated_at':    datetime.now(timezone.utc).isoformat(),
                'meta':          {'tier': 'baseline', 'error': str(e)[:120]},
            }), 200

    # ────────────────────────────────────────────────────────────
    # GET /api/cascade-convergence/details
    # ────────────────────────────────────────────────────────────
    @app.route('/api/cascade-convergence/details', methods=['GET'])
    def cascade_convergence_details():
        try:
            articles = _gather_articles()
            cascade_results = detect_all_cascades(articles)
            agg = aggregate_cascade_convergence(cascade_results)
            bluf = build_cascade_bluf(cascade_results, agg)
            return jsonify({
                'bluf':              bluf,
                'aggregation':       agg,
                'cascade_results':   cascade_results,
                'chains_registered': list(CASCADE_CHAINS.keys()),
                'article_count':     len(articles),
                'detector_version':  __version__,
                'updated_at':        datetime.now(timezone.utc).isoformat(),
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)[:200]}), 500

    # ────────────────────────────────────────────────────────────
    # GET /api/cascade-convergence/health
    # ────────────────────────────────────────────────────────────
    @app.route('/api/cascade-convergence/health', methods=['GET'])
    def cascade_convergence_health():
        return jsonify({
            'module':            __module_id__,
            'version':           __version__,
            'chains_registered': list(CASCADE_CHAINS.keys()),
            'chain_count':       len(CASCADE_CHAINS),
            'status':            'operational',
        }), 200

    print('[Cascade Detector] Routes registered: /api/cascade-convergence/bluf, /details, /health')


# ============================================================
# MODULE METADATA
# ============================================================
__version__ = '1.0.0'
__module_id__ = 'cascade_detector'
print(f'[Cascade Detector] Module loaded -- v{__version__}')
