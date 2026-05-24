"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — COMMODITY SIGNAL INTERPRETER
  v1.0.0  (May 24 2026)
═══════════════════════════════════════════════════════════════════════

ANALYTICAL PROSE LAYER for the commodity tracker, mirroring the pattern
established by `military_signal_interpreter.py`.

Surfaces three things at the top of commodities.html:

  1. EXECUTIVE SUMMARY  — single-paragraph BLUF synthesizing the most
                          escalatory commodity + region + convergence
                          signals visible right now.

  2. BUTTERFLY CONVERGENCES (cross-region cascades) — reads from
                          convergence_registry to surface coupled-
                          pressure fingerprints currently firing,
                          plus secondary "upstream stressor" surfacing
                          via the butterfly_reader when available.

  3. REGIONAL PRESSURE   — alphabetical-canon regions:
                            Africa
                            Asia & The Pacific
                            Europe
                            The Middle East & North Africa
                            The Western Hemisphere
                          + Global / Macro
                          Each region gets a prose synthesis of which
                          commodities are pressuring it most.

INPUT:
  scan_result : the dict returned by scan_commodity_pressure().
                Expects keys: 'commodity_summaries', 'country_summaries',
                'top_signals', 'total_signals_detected', etc.

OUTPUT:
  build_full_commodity_interpretation(scan_result) returns:
    {
      'executive_summary':    str,
      'butterfly_prose':      dict[id -> {prose, level, active, ...}],
      'regional_prose':       dict[region_key -> {prose, level, ...}],
      'interpreter_version':  '1.0.0',
    }

DESIGN PRINCIPLES (lifted from military interpreter):
  - Soft-fail everywhere. A missing field returns "" or default; never
    raises. The card on commodities.html must render even with partial
    scan data.
  - Convergence-not-prediction framing. We describe what signals are
    present; we do not forecast outcomes.
  - Plain English. The reader is a senior FSO scanning at altitude — no
    jargon without unpacking.
"""

from __future__ import annotations
from datetime import datetime, timezone

INTERPRETER_VERSION = '1.0.0'

# ══════════════════════════════════════════════════════════════
# REGION CANON (alphabetical, full diplomatic names per Coco)
# ══════════════════════════════════════════════════════════════
# Internal key  : display_name  :  short tag  :  icon
# 'global' is a synthetic region for macro signals not anchored to
# any single theatre (gold, dollar/Treasury cross-pressure, OPEC+
# narratives, dedollarization, financial-system fragmentation).
REGIONAL_DISPLAY = {
    'africa':   {
        'display': 'Africa',
        'tag':     'AFRICA / AFRICOM',
        'icon':    '\U0001f5fa',                  # 🗺
    },
    'asia':     {
        'display': 'Asia & The Pacific',
        'tag':     'ASIA & THE PACIFIC / INDOPACOM',
        'icon':    '\U0001f3ef',                  # 🏯
    },
    'europe':   {
        'display': 'Europe',
        'tag':     'EUROPE / EUCOM',
        'icon':    '\U0001f3f0',                  # 🏰
    },
    'me':       {
        'display': 'The Middle East & North Africa',
        'tag':     'MIDDLE EAST & NORTH AFRICA / CENTCOM',
        'icon':    '\U0001f54c',                  # 🕌
    },
    'wha':      {
        'display': 'The Western Hemisphere',
        'tag':     'WESTERN HEMISPHERE / SOUTHCOM-NORTHCOM',
        'icon':    '\U0001f5fd',                  # 🗽
    },
    'global':   {
        'display': 'Global / Macro',
        'tag':     'GLOBAL / MACRO',
        'icon':    '\U0001f30d',                  # 🌍
    },
}

# Canonical sort order (alphabetical-canon as per Coco's
# diplomatic naming convention; Global last because it's the
# meta-aggregate, not a peer theatre).
REGION_SORT_ORDER = ['africa', 'asia', 'europe', 'me', 'wha', 'global']

# Map from country_id (as used in commodity_tracker.COUNTRY_COMMODITY_EXPOSURE)
# to its primary commodity-tracker region. This mapping intentionally
# overlaps with the convergence_registry 'trigger_region' values so we
# can join the two datasets cleanly.
#
# Countries that DON'T appear here will be treated as 'global' (macro).
COUNTRY_TO_REGION = {
    # ── Africa ──────────────────────────────────────────
    'drc':           'africa',
    'south_africa':  'africa',
    'morocco':       'africa',
    'sudan':         'africa',
    'libya':         'africa',
    'nigeria':       'africa',
    'algeria':       'africa',
    'tunisia':       'africa',
    'egypt':         'africa',
    'ethiopia':      'africa',
    'kenya':         'africa',
    'tanzania':      'africa',
    'zimbabwe':      'africa',

    # ── Asia & The Pacific ──────────────────────────────
    'china':         'asia',
    'taiwan':        'asia',
    'japan':         'asia',
    'south_korea':   'asia',
    'north_korea':   'asia',
    'india':         'asia',
    'pakistan':      'asia',
    'indonesia':     'asia',
    'australia':     'asia',
    'philippines':   'asia',
    'vietnam':       'asia',
    'thailand':      'asia',
    'malaysia':      'asia',
    'singapore':     'asia',
    'bangladesh':    'asia',
    'mongolia':      'asia',

    # ── Europe ──────────────────────────────────────────
    'russia':        'europe',
    'ukraine':       'europe',
    'germany':       'europe',
    'france':        'europe',
    'uk':            'europe',
    'poland':        'europe',
    'hungary':       'europe',
    'belarus':       'europe',
    'greenland':     'europe',
    'denmark':       'europe',
    'netherlands':   'europe',
    'italy':         'europe',
    'spain':         'europe',
    'norway':        'europe',
    'sweden':        'europe',
    'finland':       'europe',

    # ── Middle East & North Africa ──────────────────────
    'iran':          'me',
    'israel':        'me',
    'saudi_arabia':  'me',
    'uae':           'me',
    'qatar':         'me',
    'kuwait':        'me',
    'oman':          'me',
    'bahrain':       'me',
    'iraq':          'me',
    'syria':         'me',
    'lebanon':       'me',
    'jordan':        'me',
    'yemen':         'me',
    'turkey':        'me',

    # ── Western Hemisphere ──────────────────────────────
    'us':            'wha',
    'united_states': 'wha',
    'mexico':        'wha',
    'venezuela':     'wha',
    'colombia':      'wha',
    'brazil':        'wha',
    'argentina':     'wha',
    'chile':         'wha',
    'peru':          'wha',
    'cuba':          'wha',
    'haiti':         'wha',
    'canada':        'wha',
}

# ── Alert-level severity ranking (used to pick "highest-pressured" sets) ──
ALERT_RANK = {
    'normal':   0,
    'open':     0,
    'monitor':  1,
    'elevated': 2,
    'high':     3,
    'surge':    4,
    'contested': 3,    # mirror of 'high' for chokepoint vocab
    'disrupted': 4,    # mirror of 'surge'
}

ALERT_DISPLAY = {
    'normal':   'NORMAL',
    'open':     'NORMAL',
    'monitor':  'MONITORED',
    'monitored':'MONITORED',
    'elevated': 'ELEVATED',
    'high':     'HIGH',
    'surge':    'SURGE',
    'contested':'CONTESTED',
    'disrupted':'DISRUPTED',
}


# ══════════════════════════════════════════════════════════════
# SAFE HELPERS
# ══════════════════════════════════════════════════════════════

def _safe_dict(d):
    return d if isinstance(d, dict) else {}


def _safe_list(lst):
    return lst if isinstance(lst, list) else []


def _alert_rank(level):
    return ALERT_RANK.get((level or '').lower(), 0)


def _alert_display(level):
    return ALERT_DISPLAY.get((level or '').lower(), (level or '').upper())


def _region_of_country(country_id):
    if not country_id:
        return 'global'
    return COUNTRY_TO_REGION.get(country_id.lower(), 'global')


def _commodity_display_name(commodity_summary):
    """Pull a clean display name from a commodity_summary entry."""
    if not isinstance(commodity_summary, dict):
        return ''
    return commodity_summary.get('name') or commodity_summary.get('id') or ''


def _natural_join(items):
    """Build a comma-separated list with 'and' before the last item."""
    items = [i for i in items if i]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f'{items[0]} and {items[1]}'
    return ', '.join(items[:-1]) + f', and {items[-1]}'


# Acronyms / abbreviations that should stay uppercase, not Title Case.
_COUNTRY_ALLCAPS = {
    'us':  'US',
    'usa': 'USA',
    'uk':  'UK',
    'uae': 'UAE',
    'drc': 'DRC',
    'eu':  'EU',
    'dprk':'DPRK',
    'rok': 'ROK',
}

# Countries with multi-word display names that don't survive a naive
# .replace('_',' ').title() — preserves the canonical diplomatic form.
_COUNTRY_DISPLAY_OVERRIDES = {
    'south_korea':   'South Korea',
    'north_korea':   'North Korea',
    'saudi_arabia':  'Saudi Arabia',
    'south_africa':  'South Africa',
    'united_states': 'United States',
}


def _pretty_country(country_id):
    """Display-safe rendering of a country_id."""
    if not country_id:
        return ''
    cid_low = country_id.lower()
    if cid_low in _COUNTRY_ALLCAPS:
        return _COUNTRY_ALLCAPS[cid_low]
    if cid_low in _COUNTRY_DISPLAY_OVERRIDES:
        return _COUNTRY_DISPLAY_OVERRIDES[cid_low]
    return country_id.replace('_', ' ').title()


# ══════════════════════════════════════════════════════════════
# EXECUTIVE SUMMARY BUILDER
# ══════════════════════════════════════════════════════════════

def build_executive_summary(scan_result):
    """
    Build a 1–3 sentence top-line BLUF for the commodity tracker.

    Strategy (in priority order):
      1. If any convergence is active, lead with the most severe one.
      2. Otherwise call out top 1-3 commodities at high/surge.
      3. Otherwise: baseline statement, no escalation.
    """
    scan_result = _safe_dict(scan_result)

    commodity_summaries = _safe_dict(scan_result.get('commodity_summaries'))
    convergences        = _safe_list(scan_result.get('active_convergences'))

    parts = []

    # ── Lead with convergence narrative if any are firing ─────────
    if convergences:
        # Sort by priority (higher = more severe)
        ranked = sorted(
            convergences,
            key=lambda c: c.get('priority', 0),
            reverse=True
        )
        top = ranked[0]
        comm = top.get('commodity') or 'multi-commodity'
        country = top.get('country') or top.get('id', '').replace('_', '-')
        parts.append(
            f"\u26a1 Cross-region convergence active: "
            f"{comm.upper()}-{country.upper()} coupled-pressure firing."
        )
        if len(ranked) >= 2:
            other_ids = [c.get('id', '').replace('_', '+').upper()
                         for c in ranked[1:3]]
            other_ids = [o for o in other_ids if o]
            if other_ids:
                parts.append(
                    f"Additional convergences active: {', '.join(other_ids)}."
                )

    # ── Surface top commodity pressure (surge / high) ─────────────
    if commodity_summaries:
        ranked = []
        for cid, summary in commodity_summaries.items():
            if not isinstance(summary, dict):
                continue
            lvl = summary.get('alert_level', 'normal')
            rank = _alert_rank(lvl)
            if rank >= 3:  # 'high' or 'surge'
                ranked.append((rank, cid, summary))
        ranked.sort(key=lambda x: (-x[0], -x[2].get('total_score', 0)))

        if ranked:
            top_three = ranked[:3]
            phrases = []
            for rank, cid, summary in top_three:
                disp = _commodity_display_name(summary) or cid
                lvl = summary.get('alert_level', '')
                phrases.append(f"{disp} at {_alert_display(lvl).lower()}")
            parts.append(
                f"Commodity pressure: {_natural_join(phrases)}."
            )

    # ── If nothing above threshold ────────────────────────────────
    if not parts:
        # Surface medium-pressure (elevated) summary so we still say
        # something useful at baseline.
        elevated = [
            (cid, summary) for cid, summary in commodity_summaries.items()
            if isinstance(summary, dict)
            and _alert_rank(summary.get('alert_level')) == 2
        ]
        if elevated:
            names = [
                _commodity_display_name(s) or cid
                for cid, s in elevated[:3]
            ]
            return (
                f"Global commodity pressure at baseline. "
                f"{_natural_join(names)} showing above-routine signal "
                f"activity but no commodity is in surge or high tier."
            )
        return (
            "Global commodity pressure at baseline. No surge-level or "
            "high-pressure signals across the 22 tracked commodities this scan."
        )

    return ' '.join(parts)


# ══════════════════════════════════════════════════════════════
# BUTTERFLY (CONVERGENCE) PROSE BUILDER
# ══════════════════════════════════════════════════════════════

def build_butterfly_prose(scan_result):
    """
    Build prose blocks for each active convergence ('butterfly effect'
    cross-region cascade), keyed by convergence ID.

    Input expected:
        scan_result['active_convergences'] = [
            {
                'id':         'wheat_lebanon',
                'commodity':  'wheat',
                'country':    'lebanon',
                'priority':   13,
                'icon':       '\U0001f33e',
                'color':      '#f59e0b',
                'headline':   'Wheat-Lebanon convergence -- ...',
                'detail':     '...long text...',
                'regions':    ['me', 'europe'],
                'alert_level':'elevated',   # from commodity at trigger
                'signals':    27,           # signal_count at trigger
                ...
            },
            ...
        ]

    Output:
        {
          '<convergence_id>': {
              'display':  'WHEAT-LEBANON',
              'icon':     '\U0001f33e',
              'level':    'elevated',
              'regions':  ['me', 'europe'],
              'prose':    '... 2-3 sentence synthesis ...',
              'priority': 13,
              'active':   True,
          },
          ...
        }
    """
    scan_result = _safe_dict(scan_result)
    convergences = _safe_list(scan_result.get('active_convergences'))

    out = {}
    if not convergences:
        return out

    # Sort by priority descending so frontend renders most-severe first
    ranked = sorted(
        convergences,
        key=lambda c: c.get('priority', 0),
        reverse=True
    )

    for conv in ranked:
        if not isinstance(conv, dict):
            continue
        cid = conv.get('id')
        if not cid:
            continue

        comm = conv.get('commodity') or 'multi-commodity'
        country = conv.get('country') or ''
        regions = _safe_list(conv.get('regions'))
        alert_level = conv.get('alert_level', 'elevated')
        signals = conv.get('signals', 0)
        headline = conv.get('headline') or ''
        detail = conv.get('detail') or ''

        # Build prose synthesis. If the registry's headline_template +
        # detail are already populated, lead with the headline (already
        # alert-substituted) and append a short context note.
        display_label = f"{comm.upper()}-{country.upper()}" if country \
            else cid.replace('_', '+').upper()

        # Prose: short headline + abbreviated context + region scope.
        # Cap detail at ~280 chars so the card stays scannable; full
        # detail is in the registry entry if user wants it on a deeper
        # endpoint later.
        detail_short = (detail[:280] + '...') if len(detail) > 280 else detail

        region_names = [
            REGIONAL_DISPLAY.get(r, {}).get('display', r.upper())
            for r in regions
        ]
        region_phrase = (
            f"Spans {_natural_join(region_names)}."
            if region_names else ''
        )

        signal_phrase = ''
        if signals:
            signal_phrase = (
                f" Currently firing on {signals} commodity signal"
                f"{'s' if signals != 1 else ''}."
            )

        prose_parts = []
        if headline:
            prose_parts.append(headline)
        if detail_short:
            prose_parts.append(detail_short)
        if region_phrase:
            prose_parts.append(region_phrase)
        if signal_phrase:
            prose_parts[-1] = (prose_parts[-1] or '') + signal_phrase

        out[cid] = {
            'display':  display_label,
            'icon':     conv.get('icon', '\u26a1'),
            'color':    conv.get('color', '#f59e0b'),
            'level':    alert_level,
            'regions':  regions,
            'priority': conv.get('priority', 0),
            'active':   True,
            'prose':    ' '.join([p for p in prose_parts if p]),
            'commodity':comm,
            'country':  country,
        }

    return out


# ══════════════════════════════════════════════════════════════
# REGIONAL PROSE BUILDER
# ══════════════════════════════════════════════════════════════

def _aggregate_region_pressure(scan_result):
    """
    Walk country_summaries and commodity_summaries; bucket pressure by
    region. Returns dict keyed by region with:
        {
          'max_alert':   highest alert_level seen in this region,
          'commodities': [(commodity_id, alert_level, score), ...],
          'countries':   [(country_id, alert_level, score), ...],
        }
    """
    scan_result = _safe_dict(scan_result)
    country_summaries   = _safe_dict(scan_result.get('country_summaries'))
    commodity_summaries = _safe_dict(scan_result.get('commodity_summaries'))

    region_state = {
        rk: {'max_alert': 'normal', 'commodities': [], 'countries': []}
        for rk in REGIONAL_DISPLAY.keys()
    }

    # ── Per-country pressure → bucket by region ──
    for cid, summary in country_summaries.items():
        if not isinstance(summary, dict):
            continue
        region = _region_of_country(cid)
        lvl = summary.get('alert_level', 'normal')
        score = summary.get('total_score', 0)
        region_state[region]['countries'].append((cid, lvl, score))
        if _alert_rank(lvl) > _alert_rank(region_state[region]['max_alert']):
            region_state[region]['max_alert'] = lvl

    # ── Per-commodity pressure → bucket each commodity into the
    #    region where its top-pressured country lives (best proxy
    #    for "this commodity is hot in this region"). ──
    for commodity_id, summary in commodity_summaries.items():
        if not isinstance(summary, dict):
            continue
        lvl = summary.get('alert_level', 'normal')
        if _alert_rank(lvl) < 2:    # skip baseline (normal/monitor)
            continue
        score = summary.get('total_score', 0)

        # Find top consumer or producer country to assign region
        candidate_countries = []
        for c in _safe_list(summary.get('top_producers'))[:3]:
            candidate_countries.append(c)
        for c in _safe_list(summary.get('top_consumers'))[:3]:
            candidate_countries.append(c)

        region_counts = {}
        for cc in candidate_countries:
            if isinstance(cc, dict):
                cc = cc.get('country') or cc.get('id')
            if not cc:
                continue
            r = _region_of_country(cc)
            region_counts[r] = region_counts.get(r, 0) + 1

        if region_counts:
            primary_region = max(region_counts.items(), key=lambda x: x[1])[0]
        else:
            primary_region = 'global'

        region_state[primary_region]['commodities'].append(
            (commodity_id, lvl, score)
        )
        if _alert_rank(lvl) > _alert_rank(region_state[primary_region]['max_alert']):
            region_state[primary_region]['max_alert'] = lvl

    return region_state


def build_regional_prose(scan_result):
    """
    Build prose blocks for each of the six regions (Africa, Asia,
    Europe, MENA, WHA, Global). Returns dict keyed by region with:
        {
          'display':       'Africa',
          'tag':           'AFRICA / AFRICOM',
          'icon':          '\U0001f5fa',
          'level':         'normal' | 'elevated' | 'high' | 'surge',
          'prose':         '... 2-3 sentence synthesis ...',
          'commodities':   [...],
          'countries':     [...],
        }

    Always returns entries for ALL 6 regions, even at baseline, so the
    frontend can render the full alphabetical-canon list.
    """
    region_state = _aggregate_region_pressure(scan_result)
    out = {}

    for region_key in REGION_SORT_ORDER:
        rdisp = REGIONAL_DISPLAY[region_key]
        state = region_state.get(region_key, {})
        max_alert = state.get('max_alert', 'normal')
        commodities = state.get('commodities', [])
        countries = state.get('countries', [])

        # Sort commodities + countries by score within the region
        commodities.sort(key=lambda x: (-_alert_rank(x[1]), -x[2]))
        countries.sort(key=lambda x: (-_alert_rank(x[1]), -x[2]))

        # ── Build prose for the region ──
        # Three flavors based on max_alert:
        #   surge / high       : "X at surge-level pressure; Y at high..."
        #   elevated           : "Z above baseline; signal classes: ..."
        #   normal / monitor   : "AOR baseline. Routine activity."

        rank = _alert_rank(max_alert)

        if rank >= 3:    # high or surge
            # Lead with hottest 2-3 commodities + countries
            hot_comm_phrases = []
            for commodity_id, lvl, _ in commodities[:3]:
                if _alert_rank(lvl) >= 2:
                    hot_comm_phrases.append(
                        f"{commodity_id.replace('_', ' ')} at "
                        f"{_alert_display(lvl).lower()} pressure"
                    )
            hot_country_phrases = []
            for cid, lvl, _ in countries[:3]:
                if _alert_rank(lvl) >= 2:
                    hot_country_phrases.append(
                        f"{_pretty_country(cid)} at "
                        f"{_alert_display(lvl).lower()}"
                    )

            lead = f"{rdisp['display']} at {_alert_display(max_alert).lower()}-level commodity pressure"
            if hot_comm_phrases:
                lead += " \u2014 " + _natural_join(hot_comm_phrases) + "."
            else:
                lead += "."
            if hot_country_phrases:
                lead += " Country exposure: " + _natural_join(hot_country_phrases) + "."
            prose = lead + (
                " Multi-commodity pressure concentrated in the AOR; "
                "watch for cascade into adjacent regions."
            )

        elif rank == 2:    # elevated
            hot_comm_phrases = [
                f"{commodity_id.replace('_', ' ')} above baseline"
                for commodity_id, lvl, _ in commodities[:2]
                if _alert_rank(lvl) >= 2
            ]
            hot_country_phrases = [
                _pretty_country(cid)
                for cid, lvl, _ in countries[:2]
                if _alert_rank(lvl) >= 2
            ]
            if hot_comm_phrases or hot_country_phrases:
                lead = f"{rdisp['display']} elevated above baseline"
                if hot_comm_phrases:
                    lead += " \u2014 " + _natural_join(hot_comm_phrases) + "."
                else:
                    lead += "."
                if hot_country_phrases:
                    lead += " Country exposure: " + _natural_join(hot_country_phrases) + "."
                prose = lead + (
                    " Above-routine commodity pressure without crossing "
                    "into high or surge thresholds."
                )
            else:
                prose = (
                    f"{rdisp['display']} elevated above baseline. "
                    f"Above-routine commodity pressure without crossing "
                    f"into high or surge thresholds."
                )

        else:    # normal / monitor
            # Distinguish 'global' (which gets a different baseline
            # phrasing) from regional baseline
            if region_key == 'global':
                prose = (
                    "Global / Macro commodity baseline. No cross-cutting "
                    "surge in dollar-sensitive, currency-divergence, or "
                    "BRICS-realignment signal classes this scan."
                )
            else:
                prose = (
                    f"{rdisp['display']} AOR commodity baseline. "
                    f"Routine activity across tracked commodities with no "
                    f"region-wide escalation signal."
                )

        out[region_key] = {
            'display':       rdisp['display'],
            'tag':           rdisp['tag'],
            'icon':          rdisp['icon'],
            'level':         max_alert,
            'prose':         prose,
            'commodities':   [
                {'id': cid, 'alert_level': lvl, 'score': sc}
                for cid, lvl, sc in commodities[:8]
            ],
            'countries':     [
                {'id': cid, 'alert_level': lvl, 'score': sc}
                for cid, lvl, sc in countries[:8]
            ],
        }

    return out


# ══════════════════════════════════════════════════════════════
# UMBRELLA BUILDER
# ══════════════════════════════════════════════════════════════

def build_full_commodity_interpretation(scan_result):
    """
    One-call wrapper. Returns the complete commodity interpretation
    package, ready to wire into scan_result['interpretation'].

    Returns:
        {
            'executive_summary':   str,
            'butterfly_prose':     dict,
            'regional_prose':      dict,
            'interpreter_version': '1.0.0',
            'generated_at':        ISO timestamp,
        }
    """
    try:
        return {
            'executive_summary':   build_executive_summary(scan_result),
            'butterfly_prose':     build_butterfly_prose(scan_result),
            'regional_prose':      build_regional_prose(scan_result),
            'interpreter_version': INTERPRETER_VERSION,
            'generated_at':        datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        # Soft-fail: return a minimal package so the frontend can render
        # a graceful-degraded state rather than an empty/null block.
        return {
            'executive_summary':   (
                'Commodity interpreter encountered a transient error. '
                'Per-commodity cards and country exposure matrix remain '
                'authoritative.'
            ),
            'butterfly_prose':     {},
            'regional_prose':      {},
            'interpreter_version': INTERPRETER_VERSION,
            'generated_at':        datetime.now(timezone.utc).isoformat(),
            'error':               str(e)[:200],
        }


# ══════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("[Commodity Interpreter] Self-test running...")

    synthetic = {
        'commodity_summaries': {
            'wheat': {
                'name':         'Wheat',
                'tier':         1,
                'alert_level':  'high',
                'total_score':  47.3,
                'signal_count': 33,
                'top_producers': ['russia', 'ukraine', 'us'],
                'top_consumers': ['china', 'india', 'egypt'],
            },
            'oil': {
                'name':         'Crude Oil',
                'tier':         1,
                'alert_level':  'surge',
                'total_score':  62.1,
                'signal_count': 51,
                'top_producers': ['saudi_arabia', 'us', 'russia'],
                'top_consumers': ['china', 'us', 'india'],
            },
            'cobalt': {
                'name':         'Cobalt',
                'tier':         2,
                'alert_level':  'elevated',
                'total_score':  18.4,
                'signal_count': 12,
                'top_producers': ['drc', 'indonesia'],
                'top_consumers': ['china', 'south_korea'],
            },
            'gold': {
                'name':         'Gold',
                'tier':         1,
                'alert_level':  'elevated',
                'total_score':  21.0,
                'signal_count': 19,
                'top_producers': ['china', 'australia', 'us'],
                'top_consumers': ['india', 'china'],
            },
        },
        'country_summaries': {
            'lebanon':       {'alert_level': 'high',     'total_score': 31.0},
            'ukraine':       {'alert_level': 'high',     'total_score': 28.5},
            'iran':          {'alert_level': 'surge',    'total_score': 42.1},
            'china':         {'alert_level': 'elevated', 'total_score': 16.0},
            'drc':           {'alert_level': 'elevated', 'total_score': 14.2},
            'us':            {'alert_level': 'elevated', 'total_score': 12.0},
        },
        'active_convergences': [
            {
                'id':          'wheat_lebanon',
                'commodity':   'wheat',
                'country':     'lebanon',
                'priority':    13,
                'icon':        '\U0001f33e',
                'color':       '#f59e0b',
                'headline':    'Wheat-Lebanon convergence -- food security crisis compounded by global wheat HIGH',
                'detail':      'Lebanon imports ~60-67% of wheat from Ukraine...',
                'regions':     ['me', 'europe'],
                'alert_level': 'high',
                'signals':     33,
            },
            {
                'id':          'hormuz_china_oil_dependency',
                'commodity':   'oil',
                'country':     'china',
                'priority':    14,
                'icon':        '\U0001f6a2',
                'color':       '#dc2626',
                'headline':    'Hormuz-China oil dependency -- coupled pressure on Asian energy security',
                'detail':      'China imports ~40% of crude through the Strait of Hormuz...',
                'regions':     ['me', 'asia'],
                'alert_level': 'surge',
                'signals':     51,
            },
        ],
        'top_signals': [],
    }

    pkg = build_full_commodity_interpretation(synthetic)

    print("\n=== EXECUTIVE SUMMARY ===")
    print(pkg['executive_summary'])

    print("\n=== BUTTERFLY PROSE ===")
    for cid, c in pkg['butterfly_prose'].items():
        print(f"  [{c['level'].upper()}] {c['display']}: {c['prose'][:140]}...")

    print("\n=== REGIONAL PROSE ===")
    for rk, r in pkg['regional_prose'].items():
        print(f"  [{r['level'].upper():>9}] {r['display']}: {r['prose'][:120]}...")

    print(f"\n=== INTERPRETER v{pkg['interpreter_version']} ===")
    print("\n\u2705 SELF-TEST COMPLETE")
