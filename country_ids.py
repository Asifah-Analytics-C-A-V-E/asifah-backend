"""
=======================================================================
  ASIFAH ANALYTICS -- COUNTRY IDENTIFIER CANON
  v1.0.0 (Oct 4 2026)
=======================================================================

ONE canonical country id for the whole platform. ONE writer, many readers.

WHY THIS FILE EXISTS
  On Oct 4 2026 a live /api/cax/scan returned 135 "countries". It was not
  135 countries. The humanitarian layer emits ISO3 codes for part of its
  roster ('sdn', 'yem', 'irn') while every other axis emits readable slugs
  ('sudan', 'yemen', 'iran'), and the convergence detector took both
  verbatim. So the same country sat in the index twice, its signals split
  between the two halves, and convergence that should have combined was
  counted as two unrelated singles.

  The measured cost in that scan:
    - 26 countries present under two or three spellings
    - IRAN reading DUAL (kinetic+rhetoric) while its humanitarian signal
      sat alone under 'irn'. Correctly joined, Iran is TRIPLE.
    - PAKISTAN the same: DUAL as 'pakistan', humanitarian orphaned as
      'pak'. Correctly joined, TRIPLE.
    - Botswana, Central African Republic, Haiti and Madagascar each split
      single/single across two ids when they are in fact DUAL.
    - DR Congo present THREE ways: 'drc', 'cod',
      'democratic_republic_of_congo'.

  Three independent normalizers already existed and disagreed with each
  other:
    convergence_detector._kinetic_name_to_id   -> 'usa',  'drc'
    global_pressure_index._norm_country        -> 'us',   'drc'
    global_pressure_index._normalize_country_name -> (n/a), 'dr congo'
  The last two live in the SAME FILE and produce different shapes --
  underscores vs spaces -- so signals routed through one path could never
  join signals routed through the other.

  This module replaces all three. Import it; do not re-implement it.

THE CANONICAL FORM
  lowercase, underscore-separated, human-readable: 'saudi_arabia', not
  'sau'; 'south_sudan', not 'ssd'. That is the convention the platform
  already uses everywhere a human reads it -- COUNTRY_COMMODITY_EXPOSURE,
  COUNTRY_META, the page filenames, SUBREGION_TO_COUNTRY. ISO3 codes are
  accepted as INPUT and translated; they are never the stored form.

USAGE
    from country_ids import canonical, display

    cid = canonical(raw_id_from_any_source)   # 'SDN' / 'sdn' / 'Sudan' -> 'sudan'
    name = display(cid)                       # 'sudan' -> 'Sudan'

  canonical() accepts anything the platform emits: ISO3 codes, readable
  slugs, GDELT display names ('DR Congo'), spaced forms ('dr congo'),
  hyphenated forms, and mixed case. It is idempotent: canonical(canonical(x))
  == canonical(x), always.

SAFETY: WHAT THIS MODULE REFUSES TO MERGE
  Country-name collapsing is where quiet, serious errors live. Four traps
  are guarded explicitly and covered by tests:
    - COG (Republic of the Congo, Brazzaville) is NOT COD (DR Congo).
    - GNB (Guinea-Bissau) is NOT GIN (Guinea).
    - NER (Niger) is NOT NGA (Nigeria).
    - SDN (Sudan) is NOT SSD (South Sudan).
  A bare 'congo' or 'korea' is AMBIGUOUS and is returned unchanged rather
  than guessed at. Silently merging two real countries is worse than
  leaving one unresolved, because the merge is invisible downstream.

OPEN DECISION (flagged, not silently resolved)
  'pse' (ISO3 for the State of Palestine) is mapped to 'palestine', a new
  canonical id. It is deliberately NOT folded into 'gaza', which on this
  platform means the Gaza Strip specifically. Folding PSE into gaza would
  silently absorb West Bank reporting into Gaza figures. If Rachel wants a
  different disposition, change the single ALIASES entry for 'pse'.
"""

COUNTRY_IDS_VERSION = '1.0.0'


# ----------------------------------------------------------------------
# Canonical id -> display name.
# Only entries whose display differs from a plain title-case of the slug
# need to be here; display() title-cases anything missing. Entries are
# included anyway where a title-case would be WRONG ('Democratic Republic
# Of Congo' with a capital 'Of', 'Uae', 'Drc').
# ----------------------------------------------------------------------
DISPLAY_NAMES = {
    'usa':            'United States',
    'united_kingdom': 'United Kingdom',
    'uae':            'United Arab Emirates',
    'drc':            'DR Congo',
    'congo_republic': 'Republic of the Congo',
    'car':            'Central African Republic',
    'eu':             'EU',
    'dprk':           'North Korea',
    'south_korea':    'South Korea',
    'south_africa':   'South Africa',
    'south_sudan':    'South Sudan',
    'saudi_arabia':   'Saudi Arabia',
    'bosnia_herzegovina': 'Bosnia and Herzegovina',
    'guinea_bissau':  'Guinea-Bissau',
    'ivory_coast':    "Côte d'Ivoire",
    'timor_leste':    'Timor-Leste',
    'sao_tome_and_principe': 'São Tomé and Príncipe',
    'saint_vincent_and_the_grenadines': 'Saint Vincent and the Grenadines',
    'the_bahamas':    'The Bahamas',
    'el_salvador':    'El Salvador',
    'costa_rica':     'Costa Rica',
    'dominican_republic': 'Dominican Republic',
    'papua_new_guinea': 'Papua New Guinea',
    'solomon_islands': 'Solomon Islands',
    'new_zealand':    'New Zealand',
    'burkina_faso':   'Burkina Faso',
    'sierra_leone':   'Sierra Leone',
    'palestine':      'Palestine',
    'gaza':           'Gaza Strip',
    'west_bank':      'West Bank',
    'czechia':        'Czechia',
    'eswatini':       'Eswatini',
    'myanmar':        'Myanmar',
    'turkey':         'Türkiye',
}


# ----------------------------------------------------------------------
# NOT COUNTRIES. These are blocs, containers or routing buckets. They may
# legitimately appear in a signal stream, but they must never be treated as
# a country in a country index. canonical() passes them through unchanged;
# is_country() returns False so callers can filter.
# ----------------------------------------------------------------------
NOT_COUNTRIES = {
    'eu', 'global', 'worldwide', 'unknown', 'regional', 'synthesis',
    'global_market', 'me', 'wha', 'europe', 'asia', 'africa', 'nato',
    'gcc', 'sahel', 'balkans', 'horn_of_africa',
}


# ----------------------------------------------------------------------
# AMBIGUOUS. A name that maps to more than one real country. canonical()
# returns these UNCHANGED and is_ambiguous() flags them, so a caller can log
# and investigate rather than inherit a silent wrong merge.
# ----------------------------------------------------------------------
AMBIGUOUS = {
    'congo',        # DR Congo or Republic of the Congo?
    'korea',        # DPRK or ROK?
    'sudan_region', # Sudan or South Sudan?
    'guinea_region',
    'ireland_island',
}


# ----------------------------------------------------------------------
# THE ALIAS MAP. Every variant the platform is known to emit -> canonical.
# Keys are stored in NORMALIZED form (lowercase, underscores, no
# punctuation) -- _normalize() puts the caller's input in that shape before
# lookup, so you do NOT need to add cased or spaced variants by hand.
#
# Organized by region so additions are easy to place. When you add a
# country, add its ISO3 and any display name you have seen in a log.
# ----------------------------------------------------------------------
ALIASES = {

    # ---------------- Middle East & North Africa ----------------
    'syr': 'syria', 'syrian_arab_republic': 'syria',
    'lbn': 'lebanon', 'lebanese_republic': 'lebanon',
    'isr': 'israel',
    'irn': 'iran', 'islamic_republic_of_iran': 'iran',
    'irq': 'iraq',
    'jor': 'jordan', 'hashemite_kingdom_of_jordan': 'jordan',
    'egy': 'egypt', 'arab_republic_of_egypt': 'egypt',
    'sau': 'saudi_arabia', 'saudi': 'saudi_arabia',
    'are': 'uae', 'emirates': 'uae', 'united_arab_emirates': 'uae',
    'qat': 'qatar',
    'kwt': 'kuwait',
    'omn': 'oman',
    'bhr': 'bahrain',
    'yem': 'yemen',
    'tur': 'turkey', 'turkiye': 'turkey', 'republic_of_turkiye': 'turkey',
    'dza': 'algeria',
    'mar': 'morocco',
    'tun': 'tunisia',
    'lby': 'libya',
    # See OPEN DECISION in the docstring before changing this line.
    'pse': 'palestine', 'state_of_palestine': 'palestine',
    'palestinian_territories': 'palestine',
    'gaza_strip': 'gaza',
    'westbank': 'west_bank',

    # ---------------- Sub-Saharan Africa ----------------
    'sdn': 'sudan',
    'ssd': 'south_sudan',
    'eth': 'ethiopia',
    'eri': 'eritrea',
    'som': 'somalia',
    'dji': 'djibouti',
    'ken': 'kenya',
    'uga': 'uganda',
    'tza': 'tanzania', 'united_republic_of_tanzania': 'tanzania',
    'rwa': 'rwanda',
    'bdi': 'burundi',
    # COD and COG are DIFFERENT COUNTRIES. Do not "simplify" these two lines.
    'cod': 'drc', 'democratic_republic_of_congo': 'drc',
    'democratic_republic_of_the_congo': 'drc', 'dr_congo': 'drc',
    'congo_kinshasa': 'drc', 'the_democratic_republic_of_the_congo': 'drc',
    'cog': 'congo_republic', 'republic_of_the_congo': 'congo_republic',
    'congo_brazzaville': 'congo_republic',
    'caf': 'car', 'central_african_republic': 'car',
    'tcd': 'chad',
    'cmr': 'cameroon',
    'nga': 'nigeria',
    'ner': 'niger',          # NOT nigeria. See the trap list.
    'mli': 'mali',
    'bfa': 'burkina_faso',
    'sen': 'senegal',
    'gmb': 'gambia', 'the_gambia': 'gambia',
    'gnb': 'guinea_bissau', 'guineabissau': 'guinea_bissau',
    'gin': 'guinea',         # NOT guinea_bissau. See the trap list.
    'sle': 'sierra_leone',
    'lbr': 'liberia',
    'civ': 'ivory_coast', 'cote_divoire': 'ivory_coast',
    'cote_d_ivoire': 'ivory_coast', 'côte_divoire': 'ivory_coast',
    'gha': 'ghana',
    'tgo': 'togo',
    'ben': 'benin',
    'mrt': 'mauritania',
    'ago': 'angola',
    'zmb': 'zambia',
    'zwe': 'zimbabwe',
    'mwi': 'malawi',
    'moz': 'mozambique',
    'mdg': 'madagascar',
    'nam': 'namibia',
    'bwa': 'botswana',
    'zaf': 'south_africa', 'republic_of_south_africa': 'south_africa',
    'lso': 'lesotho',
    'swz': 'eswatini', 'swaziland': 'eswatini',
    'com': 'comoros',
    'stp': 'sao_tome_and_principe', 'sao_tome': 'sao_tome_and_principe',
    'mus': 'mauritius',
    'ssa': 'south_sudan',

    # ---------------- Europe ----------------
    'ukr': 'ukraine',
    'rus': 'russia', 'russian_federation': 'russia',
    'blr': 'belarus',
    'mda': 'moldova', 'republic_of_moldova': 'moldova',
    'pol': 'poland',
    'deu': 'germany',
    'fra': 'france',
    'gbr': 'united_kingdom', 'uk': 'united_kingdom', 'britain': 'united_kingdom',
    'great_britain': 'united_kingdom',
    'esp': 'spain',
    'ita': 'italy',
    'prt': 'portugal',
    'nld': 'netherlands', 'holland': 'netherlands',
    'bel': 'belgium',
    'aut': 'austria',
    'che': 'switzerland',
    'swe': 'sweden',
    'nor': 'norway',
    'fin': 'finland',
    'dnk': 'denmark',
    'isl': 'iceland',
    'irl': 'ireland',
    'grc': 'greece',
    'hun': 'hungary',
    'rou': 'romania',
    'bgr': 'bulgaria',
    'cze': 'czechia', 'czech_republic': 'czechia',
    'svk': 'slovakia',
    'svn': 'slovenia',
    'hrv': 'croatia',
    'srb': 'serbia',
    'bih': 'bosnia_herzegovina', 'bosnia': 'bosnia_herzegovina',
    'bosnia_and_herzegovina': 'bosnia_herzegovina',
    'mkd': 'north_macedonia',
    'alb': 'albania',
    'mne': 'montenegro',
    'xkx': 'kosovo',
    'grl': 'greenland',
    'cyp': 'cyprus',
    'mlt': 'malta',
    'est': 'estonia', 'lva': 'latvia', 'ltu': 'lithuania',

    # ---------------- Caucasus & Central Asia ----------------
    'arm': 'armenia',
    'aze': 'azerbaijan',
    'geo': 'georgia',
    'kaz': 'kazakhstan',
    'uzb': 'uzbekistan',
    'tkm': 'turkmenistan',
    'kgz': 'kyrgyzstan',
    'tjk': 'tajikistan',
    'afg': 'afghanistan',

    # ---------------- Asia & Pacific ----------------
    'chn': 'china', "people's_republic_of_china": 'china',
    'peoples_republic_of_china': 'china',
    'twn': 'taiwan',
    'jpn': 'japan',
    'kor': 'south_korea', 'republic_of_korea': 'south_korea',
    'prk': 'dprk', 'north_korea': 'dprk',
    'democratic_peoples_republic_of_korea': 'dprk',
    'ind': 'india',
    'pak': 'pakistan',
    'bgd': 'bangladesh',
    'npl': 'nepal',
    'lka': 'sri_lanka',
    'btn': 'bhutan',
    'mdv': 'maldives',
    'mmr': 'myanmar', 'burma': 'myanmar', 'myanmar_burma': 'myanmar',
    'tha': 'thailand',
    'vnm': 'vietnam', 'viet_nam': 'vietnam',
    'khm': 'cambodia',
    'lao': 'laos', 'lao_pdr': 'laos',
    "lao_people's_democratic_republic": 'laos',
    'laos_peoples_democratic_republic': 'laos',
    'mys': 'malaysia',
    'sgp': 'singapore',
    'idn': 'indonesia',
    'phl': 'philippines',
    'brn': 'brunei',
    'tls': 'timor_leste', 'east_timor': 'timor_leste',
    'aus': 'australia',
    'nzl': 'new_zealand',
    'png': 'papua_new_guinea',
    'slb': 'solomon_islands',
    'fji': 'fiji',
    'ton': 'tonga',
    'vut': 'vanuatu',
    'wsm': 'samoa',
    'kir': 'kiribati',
    'mng': 'mongolia',

    # ---------------- Western Hemisphere ----------------
    'usa': 'usa', 'us': 'usa', 'united_states': 'usa',
    'united_states_of_america': 'usa', 'america': 'usa',
    'can': 'canada',
    'mex': 'mexico',
    'gtm': 'guatemala',
    'hnd': 'honduras',
    'slv': 'el_salvador',
    'nic': 'nicaragua',
    'cri': 'costa_rica',
    'pan': 'panama',
    'cub': 'cuba',
    'hti': 'haiti',
    'dom': 'dominican_republic',
    'jam': 'jamaica',
    'bhs': 'the_bahamas', 'bahamas': 'the_bahamas',
    'vct': 'saint_vincent_and_the_grenadines',
    'st_vincent': 'saint_vincent_and_the_grenadines',
    'tto': 'trinidad_and_tobago',
    'col': 'colombia',
    'ven': 'venezuela',
    'venezuela_bolivarian_republic_of': 'venezuela',
    'guy': 'guyana',
    'sur': 'suriname',
    'ecu': 'ecuador',
    'per': 'peru',
    'bol': 'bolivia', 'bolivia_plurinational_state_of': 'bolivia',
    'bra': 'brazil',
    'pry': 'paraguay',
    'ury': 'uruguay',
    'arg': 'argentina',
    'chl': 'chile',
}


# ----------------------------------------------------------------------
# Normalization + lookup
# ----------------------------------------------------------------------
_PUNCT_STRIP = ".,'’()[]{}"


def _normalize(raw):
    """
    Put any inbound spelling into the shape the ALIASES keys use:
    lowercase, underscores for spaces and hyphens, punctuation stripped.

    'DR Congo'   -> 'dr_congo'
    'U.S.'       -> 'us'
    ' Sudan  '   -> 'sudan'
    'Côte-d Ivoire' -> 'côte_d_ivoire'
    """
    if raw is None:
        return ''
    s = str(raw).strip().lower()
    for ch in _PUNCT_STRIP:
        s = s.replace(ch, '')
    s = s.replace('-', '_').replace(' ', '_')
    while '__' in s:
        s = s.replace('__', '_')
    return s.strip('_')


def canonical(raw):
    """
    The one function. Any inbound country spelling -> the platform's
    canonical id.

    Guarantees:
      - idempotent: canonical(canonical(x)) == canonical(x)
      - an UNKNOWN id is returned normalized but otherwise unchanged, never
        guessed at and never dropped
      - an AMBIGUOUS name is returned unchanged (see AMBIGUOUS)
      - a non-country bucket ('global', 'eu') is returned unchanged;
        use is_country() to filter those out
    """
    n = _normalize(raw)
    if not n:
        return ''
    if n in AMBIGUOUS:
        return n
    if n in NOT_COUNTRIES:
        return n
    # One hop only. The map is authored so that every value is already
    # canonical; a second hop would let a typo build a chain.
    return ALIASES.get(n, n)


def display(cid):
    """Canonical id -> human display name."""
    c = canonical(cid)
    if not c:
        return ''
    if c in DISPLAY_NAMES:
        return DISPLAY_NAMES[c]
    return c.replace('_', ' ').title()


def is_country(cid):
    """False for blocs, containers and routing buckets ('eu', 'global')."""
    return canonical(cid) not in NOT_COUNTRIES


def is_ambiguous(raw):
    """True if this name maps to more than one real country and was NOT merged."""
    return _normalize(raw) in AMBIGUOUS


def canonical_map(ids):
    """
    {original_id: canonical_id} for a collection. Convenience for callers
    that need to report what changed, not just apply it.
    """
    return {i: canonical(i) for i in ids}


def audit(ids):
    """
    Diagnostic. Given the ids one scan produced, report what collapses.

    Returns:
      {
        'input_count':      int,
        'canonical_count':  int,
        'collisions':       {canonical: [original, ...]},   # 2+ originals
        'unmapped':         [ids that are not in ALIASES and not canonical
                              targets -- i.e. nothing recognised them],
        'ambiguous':        [...],
        'not_countries':    [...],
      }

    Re-run this after any scan. A new entry in 'collisions' means a module
    started emitting a new spelling; a new entry in 'unmapped' means a
    country arrived that this file has never seen.
    """
    by_canon = {}
    for i in ids:
        by_canon.setdefault(canonical(i), []).append(i)

    known_targets = set(ALIASES.values()) | set(DISPLAY_NAMES)
    unmapped = []
    for i in ids:
        n = _normalize(i)
        if n in ALIASES or n in known_targets or n in NOT_COUNTRIES or n in AMBIGUOUS:
            continue
        unmapped.append(i)

    return {
        'input_count':     len(list(ids)),
        'canonical_count': len(by_canon),
        'collisions':      {c: sorted(v) for c, v in sorted(by_canon.items())
                            if len(v) > 1},
        'unmapped':        sorted(unmapped),
        'ambiguous':       sorted({i for i in ids if is_ambiguous(i)}),
        'not_countries':   sorted({canonical(i) for i in ids if not is_country(i)}),
        'version':         COUNTRY_IDS_VERSION,
    }
