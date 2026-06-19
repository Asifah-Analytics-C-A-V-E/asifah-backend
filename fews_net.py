"""
fews_net.py
Asifah Analytics -- Shared Humanitarian Data Module (ME backend)
v1.0.0 -- June 19, 2026

CANONICAL FEWS NET FOOD-SECURITY LAYER
======================================
Single source of truth for IPC / Population-in-Need (PIN) food-security data,
transcribed from FEWS NET's Food Assistance Outlook Brief (FAOB) and the
FAO-WFP Hunger Hotspots cycle. This module is DATA + ACCESSORS only -- it does
no scraping and holds no Flask state, so every consumer imports it cleanly:

  - syria_humanitarian.py  -> get_panel('syria') for the Food Security card
  - <country>_humanitarian / africa stability pages -> get_panel(<code>)
  - humanitarian_convergence_detector.py -> famine_risk_countries() +
    high_severity_countries() to SEED the convergence (news then amplifies)

WHY A SHARED MODULE (not inside syria_humanitarian.py):
  FEWS NET is global. Embedding it in one country's module would force every
  other consumer to import that country. This mirrors convergence_registry.py:
  one canonical dataset, many readers.

DATA HONESTY (platform standard):
  Every country record carries `source`, `source_url`, and `source_as_of`.
  Figures are reconciled from the June 2026 FAOB, recent FAOBs (Feb-May 2026),
  and the June 2026 FAO-WFP Hunger Hotspots report. Where a figure predates the
  June FAOB it is dated in `source_as_of`. The ~23 lower-severity presence
  countries are scaffolded with `data_pending=True` until transcribed from the
  June FAOB PDF -- they are intentionally NOT given invented numbers.

  PIN = population projected to be in Crisis (IPC Phase 3) or worse BEFORE any
  planned assistance. "risk_of_famine" is FEWS NET's credible-alternative-
  scenario flag: Famine (IPC Phase 5) is plausible but NOT the most-likely
  area outcome -- so `highest_ipc_phase` (most likely) and `risk_of_famine`
  (the Phase 5 alternative) are stored SEPARATELY, per FEWS NET methodology.

CADENCE: refresh each FAOB cycle (~monthly). Bump META['cycle'] + as_of.
"""

# ============================================================
# MODULE METADATA
# ============================================================
META = {
    'cycle':        'June 2026',
    'source':       'FEWS NET Food Assistance Outlook Brief (FAOB) + FAO-WFP Hunger Hotspots',
    'source_url':   'https://fews.net/global/food-assistance-outlook-brief/june-2026',
    'data_as_of':   '2026-06',
    'global_pin':   '120-130 million',  # total PIN across FEWS NET presence countries (FAOB)
    'global_note':  ('Iran-war Hormuz fuel/fertilizer squeeze + 61-87% El Nino probability '
                     '(mid-2026) are compounding drivers across import-dependent theatres.'),
    'disclaimer':   ('Food-security reads are PIN/IPC projections, not forecasts of famine. '
                     'risk_of_famine flags a credible alternative scenario, not the most-likely outcome.'),
}

# IPC area-level classification reference (highest area classification per country)
IPC_PHASES = {
    1: 'Minimal',
    2: 'Stressed',
    3: 'Crisis',
    4: 'Emergency',
    5: 'Famine',
}

# ============================================================
# COUNTRY RECORDS -- headline severity (June 2026, attributed)
# ============================================================
# Keyed by Asifah country code (aligns with convergence detector COUNTRY_PATTERNS).
FEWS_COUNTRIES = {

    'sudan': {
        'name':              'Sudan',
        'region':            'east_africa',
        'pin':               '19.5M',
        'pin_numeric':       19_500_000,
        'pct_population':    '41%',
        'highest_ipc_phase': 4,
        'phase4_pin':        '5M',
        'risk_of_famine':    True,
        'famine_risk_areas': ('14 areas across North Darfur, South Darfur, South Kordofan '
                              'through Sep 2026; 13 areas persist through Jan 2027'),
        'trend':             'worse',
        'global_pin_share':  'over 10% of global PIN (top-4)',
        'key_shocks':        ['conflict', 'displacement', 'economic_crisis'],
        'notes':             ('Largest food crisis in the dataset. Siege dynamics, mass '
                              'displacement, and collapsed markets drive the famine-risk areas.'),
        'source':            'FAO-WFP Hunger Hotspots (Jun 2026); FEWS NET FAOB',
        'source_url':        'https://fews.net/east-africa/sudan',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'south_sudan': {
        'name':              'South Sudan',
        'region':            'east_africa',
        'pin':               'Highest share of population in dataset',
        'pin_numeric':       None,
        'pct_population':    '55-60%',
        'highest_ipc_phase': 4,
        'risk_of_famine':    True,
        'famine_risk_areas': 'Jonglei / Upper Nile and conflict-affected counties (FAOB scenario)',
        'trend':             'worse',
        'global_pin_share':  'top-5 PIN',
        'key_shocks':        ['conflict', 'flooding', 'economic_crisis'],
        'notes':             ('Highest PIN as a share of total population of any FEWS NET '
                              'country (55-60%). Conflict + flooding + macroeconomic collapse.'),
        'source':            'FEWS NET FAOB (May-Jun 2026)',
        'source_url':        'https://fews.net/east-africa/south-sudan',
        'source_as_of':      '2026-05',
        'data_pending':      False,
    },

    'somalia': {
        'name':              'Somalia',
        'region':            'east_africa',
        'pin':               '~6M',
        'pin_numeric':       6_000_000,
        'pct_population':    '25-30%',
        'highest_ipc_phase': 4,
        'phase4_pin':        '~1.9M',
        'risk_of_famine':    True,
        'famine_risk_areas': 'Burhakaba District (Bay region); drought-hit south',
        'trend':             'worse',
        'key_shocks':        ['drought', 'el_nino', 'conflict', 'crop_failure'],
        'notes':             ('Bay region breadbasket withering from rainfall deficits; record-low '
                              'crop production. Imported rice prices up on Iran-war shipping disruption.'),
        'source':            'FAO-WFP Hunger Hotspots (Jun 2026); FEWS NET FAOB',
        'source_url':        'https://fews.net/east-africa/somalia',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'drc': {
        'name':              'Democratic Republic of the Congo',
        'region':            'southern_africa',
        'pin':               'Top-4 PIN (over 10% of global total)',
        'pin_numeric':       None,
        'pct_population':    None,
        'highest_ipc_phase': 4,
        'risk_of_famine':    False,
        'trend':             'worse',
        'global_pin_share':  'over 10% of global PIN (top-4)',
        'key_shocks':        ['conflict', 'displacement', 'disease_outbreak'],
        'health_overlay':    ('Ebola outbreak (since May 2026): epicenter Ituri, plus North/South '
                              'Kivu; Rwanda-Uganda border closures disrupting cross-border trade.'),
        'notes':             ('Eastern conflict (M23/Kivu) + one of the largest PINs globally + an '
                              'active Ebola overlay. Cross-references the cobalt-DRC commodity layer.'),
        'source':            'FEWS NET FAOB (May-Jun 2026); FAO-WFP Hunger Hotspots',
        'source_url':        'https://fews.net/southern-africa/democratic-republic-congo',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'nigeria': {
        'name':              'Nigeria',
        'region':            'west_africa',
        'pin':               'Top-4 PIN (over 10% of global total)',
        'pin_numeric':       None,
        'pct_population':    None,
        'highest_ipc_phase': 4,
        'risk_of_famine':    True,
        'famine_risk_areas': 'Borno State -- populations may face Catastrophe (IPC Phase 5)',
        'trend':             'worse',
        'global_pin_share':  'over 10% of global PIN (top-4)',
        'key_shocks':        ['conflict', 'economic_crisis', 'displacement'],
        'notes':             ('Added to highest-concern tier: Borno State (NE) projected to risk '
                              'Catastrophe outcomes amid insurgency + naira-driven price shocks.'),
        'source':            'FAO-WFP Hunger Hotspots (Jun 2026); FEWS NET FAOB',
        'source_url':        'https://fews.net/west-africa/nigeria',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'yemen': {
        'name':              'Yemen',
        'region':            'east_africa',  # FEWS NET groups Yemen under East Africa
        'pin':               'Top PIN tier',
        'pin_numeric':       None,
        'pct_population':    '35-40%',
        'highest_ipc_phase': 4,
        'risk_of_famine':    False,
        'trend':             'similar',
        'key_shocks':        ['conflict', 'economic_crisis', 'import_dependence'],
        'notes':             ('Among the highest PIN shares (35-40%). Acutely exposed to Red Sea / '
                              'Hormuz shipping and fuel-price shocks as a near-total food importer.'),
        'source':            'FEWS NET FAOB (May 2026)',
        'source_url':        'https://fews.net/east-africa/yemen',
        'source_as_of':      '2026-05',
        'data_pending':      False,
    },

    'haiti': {
        'name':              'Haiti',
        'region':            'lac',
        'pin':               'High severity',
        'pin_numeric':       None,
        'pct_population':    '25-30%',
        'highest_ipc_phase': 4,
        'risk_of_famine':    False,
        'trend':             'worse',
        'key_shocks':        ['armed_violence', 'displacement', 'economic_crisis', 'import_dependence'],
        'notes':             ('Emergency (IPC Phase 4) in areas of Port-au-Prince and among IDPs; '
                              'gang control of supply routes + import dependence.'),
        'source':            'FEWS NET FAOB (Mar-May 2026)',
        'source_url':        'https://fews.net/latin-america-and-caribbean/haiti',
        'source_as_of':      '2026-05',
        'data_pending':      False,
    },

    'chad': {
        'name':              'Chad',
        'region':            'west_africa',
        'pin':               'Elevated (refugee-driven)',
        'pin_numeric':       None,
        'pct_population':    None,
        'highest_ipc_phase': 3,
        'risk_of_famine':    False,
        'trend':             'worse',
        'key_shocks':        ['refugee_influx', 'conflict_spillover', 'food_prices'],
        'notes':             ('Crisis (IPC Phase 3) in Ouaddai, Sila, Wadi Fira, Ennedi-Est from the '
                              'Sudanese refugee influx + Chadian returnees; Lac Province Crisis from conflict.'),
        'source':            'FEWS NET FAOB (Feb-Jun 2026)',
        'source_url':        'https://fews.net/west-africa/chad',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'mali': {
        'name':              'Mali',
        'region':            'west_africa',
        'pin':               'Higher than last year',
        'pin_numeric':       None,
        'pct_population':    None,
        'highest_ipc_phase': 4,
        'risk_of_famine':    False,
        'trend':             'worse',
        'key_shocks':        ['conflict', 'blockade', 'fertilizer_costs'],
        'notes':             ('Emergency (IPC Phase 4) risk in the north (Kidal) amid blockade '
                              'dynamics; fertilizer costs elevated by the Middle East escalation.'),
        'source':            'FEWS NET FAOB (May-Jun 2026)',
        'source_url':        'https://fews.net/west-africa/mali',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'burundi': {
        'name':              'Burundi',
        'region':            'east_africa',
        'pin':               'Higher than last year',
        'pin_numeric':       None,
        'pct_population':    None,
        'highest_ipc_phase': 3,
        'risk_of_famine':    False,
        'trend':             'worse',
        'key_shocks':        ['economic_crisis', 'displacement', 'fuel_shortage'],
        'notes':             'Macroeconomic stress + fuel scarcity; receives displacement from DRC.',
        'source':            'FEWS NET FAOB (May-Jun 2026)',
        'source_url':        'https://fews.net/east-africa/burundi',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'lebanon': {
        'name':              'Lebanon',
        'region':            'middle_east',
        'pin':               'Crisis in the south',
        'pin_numeric':       None,
        'pct_population':    None,
        'highest_ipc_phase': 3,
        'risk_of_famine':    False,
        'trend':             'worse',
        'key_shocks':        ['conflict', 'economic_crisis', 'refugee_hosting'],
        'notes':             ('Crisis (IPC Phase 3) in southern Lebanon from renewed conflict-related '
                              'displacement; WFP cut cash aid to Syrian refugee households (May 2026). '
                              'Cross-references the wheat-Lebanon convergence.'),
        'source':            'FEWS NET FAOB (Mar-Jun 2026)',
        'source_url':        'https://fews.net/middle-east-and-asia/lebanon',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },

    'syria': {
        'name':              'Syria',
        'region':            'middle_east',
        'pin':               '7.2M acutely food insecure',
        'pin_numeric':       7_200_000,
        'pct_population':    '~30%',
        'highest_ipc_phase': 3,
        'phase4_pin':        '1.6M in severe / Emergency conditions',
        'risk_of_famine':    False,
        'trend':             'similar',
        'key_shocks':        ['conflict_legacy', 'economic_crisis', 'aid_withdrawal'],
        'aid_disruption':    ('WFP HALVED emergency food aid May 2026 (1.3M -> 650,000 recipients; '
                              '14 governorates -> 7) and HALTED the nationwide bread subsidy that fed '
                              'up to 4M/day via 300+ bakeries. Driven by funding cuts, not reduced need. '
                              'WFP needs $189M (Jun-Nov). Refugee aid also cut in Jordan/Egypt/Lebanon.'),
        'notes':             ('Needs persist despite post-Assad stabilization; the aid withdrawal is '
                              'the dominant 2026 driver. Lean season (January) is the near-term inflection.'),
        'source':            'WFP (May 13 2026); FEWS NET FAOB',
        'source_url':        'https://fews.net/middle-east-and-asia/syria',
        'source_as_of':      '2026-06',
        'data_pending':      False,
    },
}

# ============================================================
# PRESENCE COUNTRIES -- canonical FEWS NET coverage set (June 2026)
# Headliners above carry full records; the rest are scaffolded for the Africa
# build and convergence dedupe. data_pending=True => transcribe from FAOB PDF.
# ============================================================
PRESENCE_COUNTRIES = {
    'east_africa':    ['burundi', 'djibouti', 'ethiopia', 'kenya', 'rwanda', 'somalia',
                       'south_sudan', 'sudan', 'tanzania', 'uganda', 'yemen'],
    'southern_africa':['angola', 'drc', 'lesotho', 'madagascar', 'malawi', 'mozambique',
                       'zambia', 'zimbabwe'],
    'west_africa':    ['benin', 'burkina_faso', 'cameroon', 'car', 'chad', 'cote_divoire',
                       'guinea', 'liberia', 'mali', 'mauritania', 'niger', 'nigeria',
                       'senegal', 'sierra_leone', 'togo'],
    'asia':           ['afghanistan', 'pakistan', 'tajikistan'],
    'middle_east':    ['gaza', 'iran', 'iraq', 'lebanon', 'syria', 'ukraine', 'yemen'],
    'lac':            ['colombia', 'ecuador', 'el_salvador', 'guatemala', 'haiti',
                       'honduras', 'nicaragua', 'venezuela'],
}

# ============================================================
# ACCESSORS
# ============================================================
def meta():
    """Module-level provenance for footers / 'data as of' lines."""
    return dict(META)


def get_country(code):
    """Full record for a country code, or None if not in the dataset."""
    return FEWS_COUNTRIES.get((code or '').lower())


def all_countries():
    """All fully-populated country records (list of dicts, code injected)."""
    out = []
    for code, rec in FEWS_COUNTRIES.items():
        r = dict(rec)
        r['code'] = code
        out.append(r)
    return out


def presence_countries():
    """Flat canonical FEWS NET coverage list (codes)."""
    seen, flat = set(), []
    for region_list in PRESENCE_COUNTRIES.values():
        for c in region_list:
            if c not in seen:
                seen.add(c)
                flat.append(c)
    return flat


def get_panel(code):
    """Compact dict for a stability-page Food Security card. Returns None if the
    country has no FEWS record yet (caller renders 'no FEWS data')."""
    rec = get_country(code)
    if not rec:
        return None
    return {
        'name':              rec['name'],
        'pin':               rec.get('pin'),
        'pct_population':    rec.get('pct_population'),
        'highest_ipc_phase': rec.get('highest_ipc_phase'),
        'ipc_label':         IPC_PHASES.get(rec.get('highest_ipc_phase'), 'Unknown'),
        'risk_of_famine':    rec.get('risk_of_famine', False),
        'famine_risk_areas': rec.get('famine_risk_areas'),
        'trend':             rec.get('trend'),
        'key_shocks':        rec.get('key_shocks', []),
        'aid_disruption':    rec.get('aid_disruption'),
        'health_overlay':    rec.get('health_overlay'),
        'notes':             rec.get('notes'),
        'source':            rec.get('source'),
        'source_url':        rec.get('source_url'),
        'source_as_of':      rec.get('source_as_of'),
        'cycle':             META['cycle'],
    }


def famine_risk_countries():
    """Codes flagged risk_of_famine -- drives the convergence famine-risk escalator."""
    return [code for code, rec in FEWS_COUNTRIES.items() if rec.get('risk_of_famine')]


def high_severity_countries(min_phase=4):
    """Codes whose highest IPC area classification >= min_phase (Emergency by default).
    These SEED the humanitarian convergence detector (news then amplifies)."""
    return [code for code, rec in FEWS_COUNTRIES.items()
            if (rec.get('highest_ipc_phase') or 0) >= min_phase]


def pin_ranking(limit=None):
    """Countries sorted by numeric PIN desc (only those with pin_numeric).
    Records without a numeric PIN are returned after, in insertion order."""
    ranked = sorted(
        all_countries(),
        key=lambda r: (r.get('pin_numeric') is not None, r.get('pin_numeric') or 0),
        reverse=True,
    )
    return ranked[:limit] if limit else ranked
