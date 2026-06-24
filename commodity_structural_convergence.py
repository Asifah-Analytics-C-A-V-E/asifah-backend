"""
commodity_structural_convergence.py  --  Asifah Analytics
================================================================
TIER-2 CONVERGENCE  --  commodity EXPOSURE x World Bank STRUCTURAL stress.

WHAT THIS IS
  The ANALYST layer reading two INDEPENDENT sensor feeds together:
    1. COMMODITY EXPOSURE  (COUNTRY_COMMODITY_EXPOSURE in commodity_tracker.py,
       static USGS/IEA/trade-sourced registry of who produces / consumes /
       transits / processes each commodity)
    2. STRUCTURAL STRESS   (worldbank:structural:latest in Redis, written by
       world_bank_gatherer.py -- inflation, thin FX reserves, food-import
       dependence, water stress, unemployment, poverty, food insecurity)

  A CONVERGENCE CELL exists where a country is BOTH exposed to a commodity AND
  carrying compound structural stress. The two signals are independently
  sourced, so a cell is a genuine convergence -- not an echo of one feed.

DOCTRINE  (analyst layer -- estimative voice, convergence-not-prediction)
  We do NOT predict supply cuts, price moves, or unrest. We report that an
  exposure signal and a structural-stress signal co-occur in the same country,
  name the precedent that pattern has historically preceded, and let the reader
  complete the inference. No probabilities, no dates, no "will". Absence stays
  honest: commodities with no exposed-and-stressed country are reported as
  having zero cells, never padded.

  This is the everyday-clothes version of the Black Swan convergence rule, and
  the Tier-2 fusion preview: alarm rises with the DIVERSITY of independent
  instruments agreeing (here: a static supply-chain map + a live macro feed),
  not with stacked severity inside one feed.

ENDPOINTS (registered via register_commodity_convergence_endpoints(app))
  GET /api/commodity-structural-convergence
        Full join: every commodity that has >=1 convergence cell.
  GET /api/commodity-structural-convergence/<commodity>
        Single-commodity detail (cells + which exposed players are calm).
  GET /api/commodity-structural-convergence/health
        Cheap hygiene: is the structural feed present + fresh.

READS   worldbank:structural:latest   (does NOT write -- pure analyst overlay)
"""

import os
import json
import requests
from datetime import datetime, timezone

# Single source of truth: import the exposure registry -- proxy, never clone.
from commodity_tracker import (
    COUNTRY_COMMODITY_EXPOSURE,
    COMMODITY_TYPES,
    _country_commodity_exposures,
)

__version__ = '1.0.0'

# ------------------------------------------------------------
# Config
# ------------------------------------------------------------
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
STRUCTURAL_CACHE_KEY = 'worldbank:structural:latest'

# Only surface GENUINE compound stress. The gatherer's stress_severity is 0-3:
#   0 none | 1 single stressor | 2 two stressors | 3 (>=3 stressors OR >=1 extreme)
# Gate at 2 so a lone elevated reading never manufactures a convergence cell.
MIN_SEVERITY = 2

CONVERGENCE_DISCLAIMER = (
    "CONVERGENCE indicator, NOT a probability of disruption. A cell means an "
    "independent commodity-exposure signal and an independent World Bank "
    "structural-stress signal are simultaneously present in the same country. "
    "It does not predict whether or when supply, price, or political disruption "
    "will occur. Exposure and stress are separately sourced; the reader completes "
    "the inference."
)

# Exposure-registry slug -> ISO-3166 alpha-3 (the gatherer keys countries by ISO3).
# 'eu' is a WB aggregate (no by_country row); Taiwan (TWN) is not a WB member --
# both simply never join, which is honest absence, not an error.
SLUG_TO_ISO3 = {
    'algeria': 'DZA', 'angola': 'AGO', 'argentina': 'ARG', 'australia': 'AUS',
    'azerbaijan': 'AZE',
    'belarus': 'BLR', 'belgium': 'BEL', 'botswana': 'BWA', 'brazil': 'BRA',
    'canada': 'CAN', 'chile': 'CHL', 'china': 'CHN', 'cuba': 'CUB',
    'drc': 'COD', 'egypt': 'EGY', 'france': 'FRA', 'germany': 'DEU', 'greece': 'GRC',
    'guinea': 'GIN', 'hungary': 'HUN', 'india': 'IND', 'indonesia': 'IDN',
    'iran': 'IRN', 'israel': 'ISR', 'japan': 'JPN', 'jordan': 'JOR',
    'kazakhstan': 'KAZ', 'lebanon': 'LBN', 'libya': 'LBY', 'malaysia': 'MYS',
    'mexico': 'MEX', 'morocco': 'MAR', 'netherlands': 'NLD', 'nigeria': 'NGA',
    'norway': 'NOR', 'panama': 'PAN', 'peru': 'PER', 'philippines': 'PHL',
    'qatar': 'QAT', 'russia': 'RUS', 'saudi_arabia': 'SAU', 'south_africa': 'ZAF',
    'south_korea': 'KOR', 'taiwan': 'TWN', 'thailand': 'THA', 'turkey': 'TUR',
    'turkmenistan': 'TKM', 'uae': 'ARE', 'ukraine': 'UKR', 'usa': 'USA',
    'venezuela': 'VEN', 'vietnam': 'VNM',
    # 'eu' intentionally omitted (aggregate, not a WB country row)
}

# Short prose labels for each World Bank stressor key.
STRESSOR_LABEL = {
    'inflation':              'elevated inflation',
    'food_insecurity':        'food insecurity',
    'water_stress':           'water stress',
    'reserves_months':        'thin FX reserves',
    'food_import_dependence': 'high food-import dependence',
    'unemployment':           'high unemployment',
    'poverty':                'extreme poverty',
}

# Roles that put a country on the SUPPLY side of a commodity vs the DEMAND side.
_SUPPLY_ROLES = {'producer', 'producer_consumer', 'component_producer', 'processor'}
_DEMAND_ROLES = {'consumer'}
_TRANSIT_ROLES = {'transit'}

# Staple foods -- stressed exposure here carries the subsistence/subsidy precedent.
STAPLE_FOODS = {'wheat', 'rice', 'corn', 'soybeans', 'sugar'}


# ------------------------------------------------------------
# Redis (read-only)
# ------------------------------------------------------------
def _redis_get_json(key):
    """GET a JSON value from Upstash REST. Mirrors world_bank_gatherer serialization."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=8,
        )
        if not resp.ok:
            return None
        raw = resp.json().get('result')
        if raw is None:
            return None
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return raw
        return raw
    except Exception as e:
        print(f"[commodity_convergence] Redis GET error ({key}): {str(e)[:80]}")
        return None


def _load_structural():
    """Return (by_country_dict, source_meta_dict). Empty dict if feed missing."""
    payload = _redis_get_json(STRUCTURAL_CACHE_KEY)
    if not isinstance(payload, dict):
        return {}, {}
    by_country = payload.get('by_country') or {}
    meta = {
        'generated_at': payload.get('generated_at'),
        'source':       payload.get('source'),
        'source_url':   payload.get('source_url'),
        'country_count': payload.get('country_count'),
    }
    return by_country, meta


# ------------------------------------------------------------
# Exposure inversion: commodity -> [exposed countries]
# ------------------------------------------------------------
def _commodity_to_countries():
    """
    Invert COUNTRY_COMMODITY_EXPOSURE into {commodity_id: [country_slug, ...]}.
    One entry per country (deduped); role/weight resolved later per cell.
    """
    out = {}
    for slug in COUNTRY_COMMODITY_EXPOSURE:
        for commodity_id, _role, _data in _iter_exposures_safe(slug):
            out.setdefault(commodity_id, set()).add(slug)
    return {c: sorted(s) for c, s in out.items()}


def _iter_exposures_safe(slug):
    """Yield (commodity_id, role, data) for a country across all its commodities."""
    profile = COUNTRY_COMMODITY_EXPOSURE.get(slug, {})
    for commodity_id in profile:
        for role, data in _country_commodity_exposures(slug, commodity_id):
            yield commodity_id, role, data


def _best_role_for(slug, commodity_id):
    """Return (role, weight, note, all_roles) picking the highest-weight role."""
    exposures = _country_commodity_exposures(slug, commodity_id)
    if not exposures:
        return None
    exposures_sorted = sorted(
        exposures, key=lambda rd: rd[1].get('weight', 0.0), reverse=True
    )
    top_role, top_data = exposures_sorted[0]
    all_roles = [r for r, _ in exposures_sorted]
    return (
        top_role,
        top_data.get('weight', 1.0),
        top_data.get('note', ''),
        all_roles,
    )


# ------------------------------------------------------------
# Stress summary + estimative read
# ------------------------------------------------------------
def _stress_summary(country_rec):
    """
    Build a short, evidence-anchored phrase from a country's stressors.
    Extremes first, with the actual reading cited; cap at 3 named stressors.
    Returns (phrase_str, named_keys_list).
    """
    stressed = country_rec.get('stressed', []) or []
    extreme = set(country_rec.get('extreme', []) or [])
    indicators = country_rec.get('indicators', {}) or {}

    # Order: extremes first, then the rest, stable within each group.
    ordered = [k for k in stressed if k in extreme] + \
              [k for k in stressed if k not in extreme]
    named = ordered[:3]

    parts = []
    for k in named:
        label = STRESSOR_LABEL.get(k, k.replace('_', ' '))
        rec = indicators.get(k, {})
        val, unit = rec.get('value'), rec.get('unit', '')
        if k in extreme and val is not None:
            parts.append(f"{label} ({val}{('' if unit == '%' else ' ')}{unit})")
        else:
            parts.append(label)
    phrase = ", ".join(parts) if parts else "compound structural stress"
    return phrase, named


def _read_for_cell(country_label, commodity_id, role, stress_phrase, has_extreme):
    """
    Role-aware, precedent-anchored, estimative read. No probabilities/dates/will.
    """
    is_food = commodity_id in STAPLE_FOODS
    name = COMMODITY_TYPES.get(commodity_id, {}).get('name', commodity_id)

    if role in _DEMAND_ROLES:
        if is_food:
            return (
                f"{country_label} is a structurally stressed {name.lower()} importer "
                f"({stress_phrase}) -- the compound pattern of staple-import reliance "
                f"plus thin domestic buffers that has historically preceded subsidy "
                f"strain and subsistence-driven unrest."
            )
        return (
            f"{country_label} is a structurally stressed {name.lower()} consumer "
            f"({stress_phrase}) -- import-dependent industrial demand meeting external "
            f"strain, the setting in which affordability shocks and supply-substitution "
            f"pressure have historically built."
        )

    if role in _TRANSIT_ROLES:
        return (
            f"{country_label}'s {name.lower()} transit role coincides with domestic "
            f"structural stress ({stress_phrase}) -- chokepoint reliability is partly a "
            f"function of the transit state's own stability."
        )

    # Supply side (producer / processor / component_producer / producer_consumer)
    if is_food:
        return (
            f"{country_label}'s role as a {name.lower()} producer coincides with "
            f"structural stress ({stress_phrase}) -- the strain under which producing "
            f"states have historically reached for export curbs to protect domestic "
            f"supply, tightening the world market."
        )
    return (
        f"{country_label}'s role as a {name.lower()} producer coincides with structural "
        f"stress ({stress_phrase}) -- external/fiscal strain of the kind that has "
        f"historically preceded export-control reflexes, output slippage, or "
        f"resource-nationalist repricing in producer states."
    )


# ------------------------------------------------------------
# Core build
# ------------------------------------------------------------
def build_convergence(min_severity=MIN_SEVERITY):
    """
    Join commodity exposure x structural stress. Returns the full analyst payload.
    """
    by_country, src_meta = _load_structural()
    structural_present = bool(by_country)

    commodity_countries = _commodity_to_countries()
    commodities_out = []
    total_cells = 0

    for commodity_id in sorted(commodity_countries):
        cmeta = COMMODITY_TYPES.get(commodity_id, {})
        cells = []
        for slug in commodity_countries[commodity_id]:
            iso3 = SLUG_TO_ISO3.get(slug)
            if not iso3:
                continue  # 'eu' aggregate -- no structural row
            rec = by_country.get(iso3)
            if not isinstance(rec, dict):
                continue  # not stressed / not covered by WB -> absence stays honest
            severity = rec.get('stress_severity', 0)
            if severity < min_severity:
                continue

            best = _best_role_for(slug, commodity_id)
            if not best:
                continue
            role, weight, note, all_roles = best

            country_label = rec.get('country_name') or slug.replace('_', ' ').title()
            stress_phrase, named = _stress_summary(rec)
            has_extreme = bool(rec.get('extreme'))

            cells.append({
                'country':        slug,
                'country_name':   country_label,
                'iso3':           iso3,
                'role':           role,
                'roles':          all_roles,
                'weight':         weight,
                'stress_severity': severity,
                'stressed':       rec.get('stressed', []),
                'extreme':        rec.get('extreme', []),
                'stress_summary': stress_phrase,
                'exposure_note':  note,
                'read':           _read_for_cell(country_label, commodity_id,
                                                 role, stress_phrase, has_extreme),
            })

        if not cells:
            continue  # commodity has no exposed-and-stressed country -> omit (honest)

        # Sort cells: severity desc, then exposure weight desc.
        cells.sort(key=lambda c: (c['stress_severity'], c['weight']), reverse=True)
        total_cells += len(cells)
        commodities_out.append({
            'commodity':  commodity_id,
            'name':       cmeta.get('name', commodity_id),
            'icon':       cmeta.get('icon', ''),
            'tier':       cmeta.get('tier'),
            'cell_count': len(cells),
            'max_severity': cells[0]['stress_severity'],
            'cells':      cells,
        })

    # Sort commodities: most cells first, then highest severity.
    commodities_out.sort(
        key=lambda c: (c['cell_count'], c['max_severity']), reverse=True
    )

    bluf = _build_bluf(commodities_out, total_cells, structural_present)

    return {
        'version':        __version__,
        'generated_at':   datetime.now(timezone.utc).isoformat(),
        'disclaimer':     CONVERGENCE_DISCLAIMER,
        'structural_feed_present': structural_present,
        'structural_source': src_meta,
        'gate':           {'min_severity': min_severity,
                           'meaning': '2 = two stressors; 3 = three+ stressors or an extreme'},
        'bluf':           bluf,
        'commodity_count_with_cells': len(commodities_out),
        'cell_count':     total_cells,
        'commodities':    commodities_out,
    }


def _build_bluf(commodities_out, total_cells, structural_present):
    """One estimative sentence summarizing the convergence picture."""
    if not structural_present:
        return ("Structural-stress feed unavailable this cycle; no convergence "
                "computed. (Absence stays honest -- this is missing data, not calm.)")
    if total_cells == 0:
        return ("No commodity currently shows an exposed-and-structurally-stressed "
                "convergence cell at the gate. Calm by this measure.")
    top = commodities_out[0]
    lead = f"{top['name']} ({top['cell_count']} cell{'s' if top['cell_count'] != 1 else ''})"
    return (
        f"{total_cells} convergence cell{'s' if total_cells != 1 else ''} across "
        f"{len(commodities_out)} commodit{'ies' if len(commodities_out) != 1 else 'y'}: "
        f"exposed players carrying independent World Bank structural stress. "
        f"Most concentrated: {lead}. Each cell pairs a supply-chain role with a live "
        f"macro-stress signal -- read together, not as a forecast."
    )


def build_single_commodity(commodity_id, min_severity=MIN_SEVERITY):
    """
    Detail for one commodity: convergence cells PLUS the exposed-but-calm players
    (so the reader sees the full exposure set, not only the alarming half).
    """
    commodity_id = (commodity_id or '').strip().lower()
    if commodity_id not in COMMODITY_TYPES:
        return None

    by_country, src_meta = _load_structural()
    cmeta = COMMODITY_TYPES.get(commodity_id, {})
    commodity_countries = _commodity_to_countries().get(commodity_id, [])

    cells, calm = [], []
    for slug in commodity_countries:
        best = _best_role_for(slug, commodity_id)
        if not best:
            continue
        role, weight, note, all_roles = best
        iso3 = SLUG_TO_ISO3.get(slug)
        rec = by_country.get(iso3) if iso3 else None
        severity = rec.get('stress_severity', 0) if isinstance(rec, dict) else 0

        if isinstance(rec, dict) and severity >= min_severity:
            country_label = rec.get('country_name') or slug.replace('_', ' ').title()
            stress_phrase, _named = _stress_summary(rec)
            cells.append({
                'country': slug, 'country_name': country_label, 'iso3': iso3,
                'role': role, 'roles': all_roles, 'weight': weight,
                'stress_severity': severity,
                'stressed': rec.get('stressed', []), 'extreme': rec.get('extreme', []),
                'stress_summary': stress_phrase, 'exposure_note': note,
                'read': _read_for_cell(country_label, commodity_id, role,
                                       stress_phrase, bool(rec.get('extreme'))),
            })
        else:
            calm.append({
                'country': slug, 'role': role, 'roles': all_roles, 'weight': weight,
                'structural_status': ('covered, below gate' if isinstance(rec, dict)
                                      else 'no WB structural row'),
            })

    cells.sort(key=lambda c: (c['stress_severity'], c['weight']), reverse=True)
    calm.sort(key=lambda c: c['weight'], reverse=True)

    return {
        'version':      __version__,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'disclaimer':   CONVERGENCE_DISCLAIMER,
        'commodity':    commodity_id,
        'name':         cmeta.get('name', commodity_id),
        'icon':         cmeta.get('icon', ''),
        'structural_source': src_meta,
        'gate':         {'min_severity': min_severity},
        'cell_count':   len(cells),
        'cells':        cells,
        'exposed_but_calm': calm,
    }


# ------------------------------------------------------------
# Flask registration (canonical Asifah pattern)
# ------------------------------------------------------------
def register_commodity_convergence_endpoints(app):
    """Register the commodity x structural convergence endpoints on `app`."""
    from flask import jsonify, request

    @app.route('/api/commodity-structural-convergence', methods=['GET', 'OPTIONS'])
    def commodity_structural_convergence():
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            sev = request.args.get('min_severity')
            min_sev = MIN_SEVERITY
            if sev is not None:
                try:
                    min_sev = max(1, min(3, int(sev)))
                except (ValueError, TypeError):
                    min_sev = MIN_SEVERITY
            return jsonify(build_convergence(min_sev)), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/commodity-structural-convergence/<commodity>',
               methods=['GET', 'OPTIONS'])
    def commodity_structural_convergence_single(commodity):
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            result = build_single_commodity(commodity)
            if result is None:
                return jsonify({'success': False,
                                'error': f"unknown commodity '{commodity}'"}), 404
            return jsonify(result), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/commodity-structural-convergence/health', methods=['GET'])
    def commodity_structural_convergence_health():
        by_country, meta = _load_structural()
        return jsonify({
            'ok':                    bool(by_country),
            'version':               __version__,
            'structural_feed_present': bool(by_country),
            'structural_generated_at': meta.get('generated_at'),
            'structural_country_count': meta.get('country_count'),
            'gate_min_severity':     MIN_SEVERITY,
            'exposure_country_count': len(COUNTRY_COMMODITY_EXPOSURE),
        }), 200

    print("[commodity_convergence] endpoints registered "
          "(/api/commodity-structural-convergence)")
