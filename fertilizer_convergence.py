"""
Fertilizer (N-P-K) Convergence Detector — Asifah Analytics
v1.0.0 — July 21, 2026  |  ME / commodities backend

SCAFFOLDING BUILD. Wired dormant now so Peru (fishmeal), potash, phosphate,
and nitrogen are ready to fire UPSTREAM the moment the Morocco phosphate build
lands. Until Morocco is built the detector still functions — it just fires on
whichever inputs are currently tracked (potash, phosphate exposure via existing
countries, natural_gas, Peru fishmeal).

═══════════════════════════════════════════════════════════════════════
THE QUESTION THIS ANSWERS
═══════════════════════════════════════════════════════════════════════
Global fertilizer / food-input security rests on FOUR concentrated pillars,
each with its own chokepoint. The GPI-worthy signal is not any one of them —
it is >=2 lighting AT ONCE (convergence, not prediction):

  N  — Nitrogen        : natural-gas-priced (ammonia/urea). Chokepoint: gas
                          (Hormuz LNG cascade, Russia/EU pipeline).
  P  — Phosphate       : ~70% Morocco/Western Sahara. Chokepoint: OCP
                          sovereign concentration + sulfur (Hormuz) for DAP/MAP.
  K  — Potash          : Belarus + Russia + Canada. Chokepoint: sanctions.
  Feed protein axis    : Peru anchoveta / fishmeal. Chokepoint: IMARPE quota
                          (the honest core of the viral 'guano collapse' story).

When two or more of these are elevated simultaneously, the read is compound
food-system input stress — the pattern that historically precedes fertilizer-
price spikes and downstream food-security pressure (Egypt, Ethiopia, Sahel
importers per WFP). Guano is NOT a pillar; it is an ecological proxy that rolls
into the fishmeal read (see commodity_tracker phosphate note).

═══════════════════════════════════════════════════════════════════════
DOCTRINE
═══════════════════════════════════════════════════════════════════════
CONVERGENCE indicator, NOT a probability of disruption. Each pillar's pressure
is INDEPENDENTLY sourced from the commodity scan; this module only reports that
>=2 are simultaneously present. It does not predict prices, shortages, or
famine. The reader completes the inference.

OUTPUT SHAPE — matches the interpreter's active_convergences schema so
build_butterfly_prose() renders it with zero interpreter changes:
  {
    'id': 'fertilizer_npk', 'commodity': 'multi-commodity', 'country': '',
    'priority': int, 'icon': str, 'color': str,
    'headline': str, 'detail': str, 'regions': [...],
    'alert_level': str, 'signals': int,
    'active_pillars': [...],  # extra field, ignored by prose builder
  }
Returns None when <2 pillars lit (dormant — absence-honest).
"""

# ── The four pillars, each mapped to the commodity id(s) that light it ──
# 'commodities' = commodity ids whose scan alert_level feeds this pillar.
# When Morocco lands, phosphate exposure deepens — no change needed here;
# the pillar already reads the 'phosphate' commodity id.
FERTILIZER_PILLARS = {
    'nitrogen': {
        'label':       'Nitrogen (gas-priced)',
        'commodities': ['natural_gas'],
        'chokepoint':  'natural gas — Hormuz LNG cascade / Russia-EU pipeline',
        'letter':      'N',
    },
    'phosphate': {
        'label':       'Phosphate (Morocco concentration)',
        'commodities': ['phosphate'],
        'chokepoint':  'OCP sovereign concentration (~70% Morocco/W. Sahara) + sulfur via Hormuz',
        'letter':      'P',
    },
    'potash': {
        'label':       'Potash (sanctions)',
        'commodities': ['potash'],
        'chokepoint':  'Belarus/Russia sanctions + Canada concentration',
        'letter':      'K',
    },
    'feed_protein': {
        'label':       'Feed protein (Peru anchoveta)',
        'commodities': ['fishmeal'],
        'chokepoint':  'Peru IMARPE anchoveta quota (Humboldt Current)',
        'letter':      'F',
    },
}

# Alert levels that count as "lit" (elevated or worse).
_LIT_LEVELS = {'elevated', 'high', 'surge', 'critical'}
_LEVEL_RANK = {'normal': 0, 'elevated': 1, 'high': 2, 'surge': 3, 'critical': 3}

ICON = '\U0001F33E\u26A1'   # 🌾⚡
COLOR = '#f59e0b'


def _commodity_alert(scan_result, commodity_id):
    """
    Pull a commodity's current alert_level from the commodity scan result.
    Tolerant of shape: looks in scan_result['commodities'][cid]['alert_level']
    then a flat scan_result['commodity_alerts'][cid]. Returns 'normal' if absent
    (absence-honest — a missing commodity never counts as lit).
    """
    if not isinstance(scan_result, dict):
        return 'normal'
    comms = scan_result.get('commodities')
    if isinstance(comms, dict):
        entry = comms.get(commodity_id)
        if isinstance(entry, dict):
            lvl = entry.get('alert_level') or entry.get('alert')
            if lvl:
                return str(lvl).lower()
    flat = scan_result.get('commodity_alerts')
    if isinstance(flat, dict) and commodity_id in flat:
        return str(flat[commodity_id]).lower()
    return 'normal'


def _pillar_is_lit(scan_result, pillar_def):
    """A pillar is lit if ANY of its commodities is at elevated+."""
    best = 'normal'
    for cid in pillar_def['commodities']:
        lvl = _commodity_alert(scan_result, cid)
        if _LEVEL_RANK.get(lvl, 0) > _LEVEL_RANK.get(best, 0):
            best = lvl
    return (best in _LIT_LEVELS), best


def build_fertilizer_convergence(scan_result):
    """
    Return a convergence dict if >=2 fertilizer pillars are lit, else None.
    Safe to call every scan — dormant until the pattern appears.
    """
    lit = []
    max_rank = 0
    for pid, pdef in FERTILIZER_PILLARS.items():
        is_lit, level = _pillar_is_lit(scan_result, pdef)
        if is_lit:
            lit.append({
                'pillar':     pid,
                'label':      pdef['label'],
                'letter':     pdef['letter'],
                'level':      level,
                'chokepoint': pdef['chokepoint'],
            })
            max_rank = max(max_rank, _LEVEL_RANK.get(level, 0))

    if len(lit) < 2:
        return None   # dormant — absence-honest

    # Composite alert = highest pillar level; priority scales with breadth.
    rank_to_level = {1: 'elevated', 2: 'high', 3: 'surge'}
    composite_level = rank_to_level.get(max_rank, 'elevated')
    # 3+ pillars OR any surge => marquee priority (15, above wheat/hormuz 13-14)
    priority = 15 if (len(lit) >= 3 or max_rank >= 3) else 13

    letters = '-'.join(p['letter'] for p in lit)
    labels = ', '.join(p['label'] for p in lit)
    pillar_names = _natural_join([p['label'].split(' (')[0] for p in lit])

    headline = (
        f"Fertilizer convergence ({letters}) — {len(lit)} food-input pillars "
        f"under simultaneous pressure"
    )
    detail = (
        f"{pillar_names} are elevated at once. Global fertilizer/food-input "
        f"security rests on four concentrated pillars (nitrogen/gas, phosphate/"
        f"Morocco, potash/sanctions, feed-protein/Peru anchoveta); simultaneous "
        f"pressure across {len(lit)} of them is the compound-stress pattern that "
        f"historically precedes fertilizer-price spikes and downstream food-"
        f"security pressure among import-dependent states (Egypt, Ethiopia, "
        f"Sahel per WFP). CONVERGENCE indicator, NOT a probability of "
        f"disruption — each pillar is independently sourced. Chokepoints: "
        + '; '.join(f"{p['letter']}={p['chokepoint']}" for p in lit) + "."
    )

    # Regions touched by the lit pillars (for the prose builder's region phrase).
    regions = ['me']  # phosphate/Morocco + Hormuz always anchor to ME
    if any(p['pillar'] == 'potash' for p in lit):
        regions.append('europe')   # Belarus/Russia
    if any(p['pillar'] == 'feed_protein' for p in lit):
        regions.append('wha')      # Peru
    regions = list(dict.fromkeys(regions))

    return {
        'id':            'fertilizer_npk',
        'commodity':     'multi-commodity',
        'country':       '',
        'priority':      priority,
        'icon':          ICON,
        'color':         COLOR,
        'headline':      headline,
        'detail':        detail,
        'regions':       regions,
        'alert_level':   composite_level,
        'signals':       len(lit),
        'active_pillars': lit,           # extra detail; prose builder ignores unknown keys
        'disclaimer':    'CONVERGENCE indicator, NOT a probability of disruption.',
    }


def _natural_join(items):
    items = [i for i in items if i]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


# ── Integration hook (call from the commodity scan, append to active_convergences) ──
def inject_fertilizer_convergence(scan_result):
    """
    Convenience: compute the fertilizer convergence and append it to
    scan_result['active_convergences'] if it fires. Call once per scan, AFTER
    per-commodity alert levels are populated. No-op when dormant.

    Usage in the commodity scan orchestrator:
        from fertilizer_convergence import inject_fertilizer_convergence
        inject_fertilizer_convergence(scan_result)   # right before interpreter
    """
    conv = build_fertilizer_convergence(scan_result)
    if conv:
        ac = scan_result.setdefault('active_convergences', [])
        if isinstance(ac, list) and not any(
            isinstance(c, dict) and c.get('id') == 'fertilizer_npk' for c in ac
        ):
            ac.append(conv)
            print(f"[Fertilizer Convergence] FIRING: {conv['signals']} pillars "
                  f"({', '.join(p['letter'] for p in conv['active_pillars'])}), "
                  f"level={conv['alert_level']}, priority={conv['priority']}")
    return scan_result


# ── Self-test (dormant + firing) ──
if __name__ == '__main__':
    # Dormant: only one pillar lit
    r1 = {'commodities': {'potash': {'alert_level': 'high'}}}
    assert build_fertilizer_convergence(r1) is None, "1 pillar should be dormant"
    print("Dormant case (1 pillar): None \u2705")

    # Firing: potash + phosphate + fishmeal
    r2 = {'commodities': {
        'potash':    {'alert_level': 'high'},
        'phosphate': {'alert_level': 'elevated'},
        'fishmeal':  {'alert_level': 'surge'},
    }}
    c = build_fertilizer_convergence(r2)
    assert c and c['signals'] == 3, "3 pillars should fire"
    assert c['priority'] == 15, "3 pillars => marquee priority 15"
    print(f"Firing case (3 pillars): priority={c['priority']}, level={c['alert_level']}")
    print(f"  Letters: {'-'.join(p['letter'] for p in c['active_pillars'])}")
    print(f"  Headline: {c['headline']}")

    # Two-pillar, elevated only
    r3 = {'commodities': {
        'natural_gas': {'alert_level': 'elevated'},
        'potash':      {'alert_level': 'elevated'},
    }}
    c3 = build_fertilizer_convergence(r3)
    assert c3 and c3['signals'] == 2 and c3['priority'] == 13
    print(f"Firing case (2 pillars, elevated): priority={c3['priority']} \u2705")
    print("\nAll self-tests passed \u2705")
