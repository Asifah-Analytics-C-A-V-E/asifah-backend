"""
humanitarian_convergence_detector.py
Asifah Analytics -- ME Backend Module
v1.6.2 -- June 22, 2026 (WB exposure/distress split: food-import is exposure; L5 needs distress)
v1.6.1 -- June 22, 2026 (WB calibration: amplifier-only gate + named mechanisms)
v1.6.0 -- June 22, 2026 (World Bank structural-stress signals)
v1.5.0 -- June 21, 2026 (UNHCR structured displacement-surge signals)
(prior: v1.4.0 May 23 2026; v1.3.0 May 19 2026; v1.0.0 May 17 2026 baseline)

GLOBAL HUMANITARIAN CONVERGENCE DETECTOR

Solves the "weak signal aggregation" problem for humanitarian crises:
no single article about Egypt vegetable prices, Ethiopia fertilizer,
or Myanmar fuel triggers anything on its own -- but the PATTERN of
distributed humanitarian distress signals across many countries IS
the canonical indicator of a global crisis forming.

ARCHITECTURE:
  Scans GDELT + RSS feeds directly for humanitarian signals from
  countries that do NOT have their own Asifah trackers yet. When
  those countries DO get trackers (per the roadmap), this layer
  continues to function as a SUPPLEMENT, not a replacement.

  Emits a BLUF-shaped payload at /api/humanitarian-convergence/bluf
  that GPI consumes as a 5th regional BLUF. GPI's existing
  pressure_type classifier picks up the humanitarian tags
  automatically — no GPI logic changes needed. Today.

SIGNAL CATEGORIES (8):
  1. FOOD_PRICE_CRISIS    -- bread/vegetable/rice price surges, food shortages
  2. FUEL_ENERGY_CRISIS   -- fuel shortages, blackouts, panic buying
  3. FERTILIZER_SCARCITY  -- planting season crisis, urea shortages
  4. AID_SHORTFALL        -- UN appeals underfunded, WFP ration cuts
  5. DISPLACEMENT_SURGE   -- IDP surges, mass displacement events
  6. CURRENCY_COLLAPSE    -- currency crashes, banking collapses, reserves drain
  7. HEALTH_EMERGENCY     -- Ebola/Marburg/cholera/mpox outbreaks, WHO PHEIC declarations,
                             pandemic warnings, disease surveillance failures (v1.4.0, May 2026)
  8. NATURAL_DISASTER     -- earthquakes/tsunamis/floods/cyclones/volcanoes/landslides/wildfires;
                             fed by USGS + GDACS + ReliefWeb disaster feed (v1.5.0, Jul 2026)

CONVERGENCE THRESHOLDS:
  1-2 countries active                  -> BASELINE       (L0-L1)
  3-5 countries active                  -> FORMING        (L3)
  6-9 countries active                  -> ACTIVE         (L4)
  10+ countries OR 4+ categories        -> GLOBAL         (L5)

ACUTE SINGLE-EVENT ELEVATION (v1.5.0):
  A high-severity acute signal (natural_disaster / health_emergency) elevates the
  region on its own -- the breadth math would otherwise bury a single catastrophe
  at baseline. One catastrophic event -> ACUTE (L4); a COMPOUND event (2+ hazard
  families, e.g. quake + tsunami) or multiple simultaneous catastrophes -> L5.

Author: RCGG / Asifah Analytics
"""
from datetime import datetime, timezone, timedelta
import json
import os
import re

# ============================================================
# SIGNAL CATEGORIES + KEYWORDS
# ============================================================
SIGNAL_CATEGORIES = {
    'food_price_crisis': {
        'label':       'Food Price Crisis',
        'icon':        '🍞',
        'description': 'Bread, vegetable, rice, or staple food price surges + shortages',
        'keywords': [
            # Generic surge language
            'food prices triple', 'food prices double', 'food prices surge',
            'food prices soar', 'food prices skyrocket', 'food inflation soar',
            'staple food shortage', 'bread shortage', 'bread price surge',
            'rice shortage', 'rice price surge', 'rice export ban',
            'flour shortage', 'flour price surge',
            'cooking oil shortage', 'cooking oil price surge',
            'vegetable prices triple', 'vegetable prices double',
            'vegetable prices surge', 'produce prices surge',
            'wheat price surge', 'grain shortage acute', 'cereal price surge',
            'sugar shortage acute', 'sugar price surge',
            'meat shortage acute', 'dairy shortage acute',
            # Crisis framing
            'food crisis acute', 'food insecurity acute',
            'acute food insecurity', 'famine warning',
            'ipc phase 3', 'ipc phase 4', 'ipc phase 5',
            'malnutrition rate', 'acute malnutrition rises',
            'food riots', 'bread riots',
            # International framing
            'wfp warning', 'fao alert', 'food security crisis',
        ],
        'high_intensity_markers': [
            'famine', 'mass starvation', 'food riots', 'ipc phase 5',
            'ipc phase 4',
        ],
    },

    'fuel_energy_crisis': {
        'label':       'Fuel / Energy Crisis',
        'icon':        '⛽',
        'description': 'Fuel shortages, blackouts, panic buying',
        'keywords': [
            'fuel shortage', 'fuel crisis acute', 'gasoline shortage',
            'diesel shortage', 'gas station closures',
            'gas station queues', 'fuel queues', 'fuel rationing',
            'panic buying fuel', 'fuel panic',
            'energy crisis acute', 'electricity blackouts', 'power blackouts',
            'rolling blackouts', 'load shedding hours',
            'natural gas shortage', 'lpg shortage',
            'fuel emergency', 'energy emergency',
            'fuel imports halted', 'fuel exports halted',
            'fuel queue deaths', 'no petrol',
        ],
        'high_intensity_markers': [
            'fuel queue deaths', 'fuel riots', 'energy emergency',
        ],
    },

    'fertilizer_scarcity': {
        'label':       'Fertilizer Scarcity',
        'icon':        '🌾',
        'description': 'Planting season fertilizer crisis, urea shortages',
        'keywords': [
            'fertilizer shortage', 'fertilizer crisis', 'fertilizer scarcity',
            'urea shortage', 'urea crisis',
            'potash shortage', 'phosphate shortage',
            'fertilizer price surge', 'fertilizer imports halted',
            'planting season fertilizer', 'farmers fertilizer crisis',
            'ammonia shortage', 'nitrogen fertilizer shortage',
            'agricultural inputs crisis', 'agri-inputs shortage',
        ],
        'high_intensity_markers': [
            'planting season missed', 'harvest collapse forecast',
        ],
    },

    'aid_shortfall': {
        'label':       'Aid Shortfall',
        'icon':        '💔',
        'description': 'UN appeals underfunded, WFP ration cuts, NGO withdrawals',
        'keywords': [
            'un appeal underfunded', 'un appeal funded only',
            'humanitarian appeal underfunded', 'wfp ration cut',
            'wfp ration cuts', 'wfp cuts rations',
            'unhcr funding shortfall', 'unhcr appeal underfunded',  # v1.4.0
            'unhcr appeal', 'unicef appeal',                        # v1.4.0
            'humanitarian funds frozen', 'usaid cuts',
            'humanitarian assistance suspended', 'aid suspended',
            'foreign aid cut', 'foreign aid suspended',
            'ngo withdrawal', 'ngo suspends operations',
            'oxfam withdrawal', 'msf withdraws', 'icrc withdrawal',
            'humanitarian funding gap', 'humanitarian budget cut',
            'humanitarian response plan underfunded',               # v1.4.0
            'cerf allocation', 'cerf appeal',                       # v1.4.0
            'state department humanitarian frozen',
            'bureau humanitarian response funds unspent',
        ],
        'high_intensity_markers': [
            'wfp ration cut', 'aid suspended', 'humanitarian funds frozen',
        ],
    },

    'displacement_surge': {
        'label':       'Displacement Surge',
        'icon':        '🚶',
        'description': 'IDP surges, mass displacement events, refugee waves',
        'keywords': [
            'mass displacement', 'mass displacement event',
            'displacement surge', 'displacement continues',     # v1.4.0
            'displaced from drc', 'displaced from sudan',       # v1.4.0
            'displaced from myanmar',                            # v1.4.0
            'idp surge', 'idp camps', 'idps displaced',
            'refugee surge', 'refugee wave', 'refugees fleeing',
            'refugees pour into', 'refugees overwhelm',          # v1.4.0
            'refugee camps overwhelmed', 'camps overwhelmed',    # v1.4.0
            'thousands displaced', 'million displaced',
            'thousands flee', 'hundreds of thousands flee',      # v1.4.0
            'displaced civilians', 'displacement crisis',
            'refugee crisis acute', 'forced displacement',
            'people on the move', 'forcibly displaced',
            'mass exodus', 'mass migration crisis',
            'humanitarian corridor', 'evacuation corridor',
            'internally displaced persons',
            'cross-border displacement',                          # v1.4.0
        ],
        'high_intensity_markers': [
            'million displaced', 'mass exodus', 'forced displacement',
        ],
    },

    'currency_collapse': {
        'label':       'Currency / Institutional Collapse',
        'icon':        '💱',
        'description': 'Currency crashes, banking collapses, FX reserves draining',
        'keywords': [
            'currency crash', 'currency collapse', 'currency plunge',
            'currency falls record', 'lira collapses', 'lebanese pound collapse',
            'foreign reserves drained', 'fx reserves critical',
            'banking collapse', 'bank run', 'bank holidays',
            'capital controls', 'capital controls imposed',
            'central bank intervention emergency', 'emergency rate hike',
            'devaluation forced', 'devaluation emergency',
            'hyperinflation', 'inflation hits record',
            'sovereign default', 'debt default',
            'imf bailout emergency', 'imf emergency loan',
        ],
        'high_intensity_markers': [
            'hyperinflation', 'sovereign default', 'banking collapse',
        ],
    },

    # ─────────────────────────────────────────────────────────────
    # v1.4.0 (May 23, 2026) -- HEALTH EMERGENCY CATEGORY
    # ─────────────────────────────────────────────────────────────
    # Surfaces disease outbreaks (Ebola, Marburg, cholera, mpox, RVF, etc.),
    # WHO PHEIC declarations, pandemic warnings, vaccine-stock failures,
    # and "disease X" pandemic-prep language. Particularly important for
    # African humanitarian context — Ebola in DRC/Uganda, Marburg in Rwanda/
    # Tanzania, cholera in Sudan/Yemen/Haiti, mpox cross-border surges.
    # Routes to GPI humanitarian axis via category-substring hints
    # ('ebola', 'marburg', 'cholera', 'mpox', 'outbreak', 'disease',
    # 'epidemic', 'pandemic', 'who_emergency', 'health_emergency').
    # ─────────────────────────────────────────────────────────────
    'health_emergency': {
        'label':       'Health Emergency / Outbreak',
        'icon':        '🦠',
        'description': 'Disease outbreaks (Ebola/Marburg/cholera/mpox), WHO emergency declarations, pandemic warnings',
        'keywords': [
            # ── Named outbreak diseases (high-priority watchlist) ──
            'ebola outbreak', 'ebola virus disease', 'ebola cases',
            'ebola death toll', 'ebola confirmed', 'ebola suspected',
            'ebola sudan strain', 'ebola zaire strain', 'sudan virus',
            'marburg outbreak', 'marburg virus disease', 'marburg cases',
            'marburg confirmed', 'mvd outbreak',
            'cholera outbreak', 'cholera cases', 'cholera epidemic',
            'cholera deaths', 'cholera vaccine shortage',
            'mpox outbreak', 'mpox cases', 'monkeypox outbreak',
            'mpox clade i', 'mpox clade ib', 'monkeypox spread',
            'rift valley fever', 'rvf outbreak',
            'lassa fever outbreak', 'crimean congo fever',
            'nipah virus', 'avian flu outbreak', 'h5n1 outbreak',
            'h5n1 human cases', 'bird flu spillover',
            # ── Outbreak language (generic) ──
            'disease outbreak', 'outbreak declared', 'outbreak confirmed',
            'epidemic declared', 'epidemic spreading', 'epidemic surge',
            'cases surge outbreak', 'mortality rate climbs',
            'case fatality rate', 'novel pathogen',
            # ── WHO emergency declarations + pandemic-prep language ──
            'who emergency declared', 'who pheic', 'pheic declared',
            'public health emergency international concern',
            'pandemic warning', 'pandemic alert', 'pandemic prep',
            'disease x', 'who director-general statement',
            'who africa region alert', 'who afro alert',
            # ── Health system stress + vaccine logistics ──
            'health system collapse', 'hospitals overwhelmed',
            'health workers strike', 'medical supply shortage',
            'vaccine shortage', 'vaccine stock-out', 'cold chain failure',
            'oral cholera vaccine shortage', 'ocv shortage',
            'medical evacuation', 'medical aid suspended',
            'icrc health mission', 'msf health response',
            # ── Specific subnational outbreaks (Africa-heavy) ──
            'kivu outbreak', 'goma outbreak', 'beni outbreak',
            'uganda ebola', 'rwanda marburg', 'tanzania marburg',
            'darfur cholera', 'khartoum cholera',
            'haiti cholera', 'yemen cholera',
            # ── Spillover + zoonotic language ──
            'zoonotic spillover', 'bat virus', 'fruit bat virus',
            'wildlife outbreak', 'spillover event',
        ],
        'high_intensity_markers': [
            # Severity-amplifying language that justifies SEVERITY_HIGH
            'pheic declared', 'who emergency declared',
            'public health emergency international concern',
            'pandemic warning', 'pandemic alert',
            'ebola outbreak', 'marburg outbreak',
            'cases surge outbreak', 'mortality rate climbs',
            'health system collapse', 'hospitals overwhelmed',
        ],
    },

    # ─────────────────────────────────────────────────────────────
    # v1.5.0 (Jul 1, 2026) -- NATURAL DISASTER CATEGORY
    # ─────────────────────────────────────────────────────────────
    # Sudden-onset natural hazards: earthquakes, tsunamis, floods, tropical
    # cyclones, volcanic eruptions, landslides, wildfires. Unlike the slow-burn
    # categories (food/displacement/currency), a single catastrophic disaster in
    # ONE country is a Global Pressure event on its own -- so this category feeds
    # the ACUTE severity floor in aggregate_convergence (single-event elevation),
    # and a COMPOUND event (quake + tsunami, etc.) elevates further. Fed by USGS
    # (structured quake GeoJSON), GDACS multi-hazard alerts, and ReliefWeb's
    # disaster feed via the gatherer. Routes to the GPI humanitarian axis exactly
    # like every other category (no GPI change).
    # ─────────────────────────────────────────────────────────────
    'natural_disaster': {
        'label':       'Natural Disaster',
        'icon':        '🌋',
        'description': 'Earthquakes, tsunamis, floods, cyclones, volcanic eruptions, landslides, and wildfires driving sudden humanitarian need',
        'keywords': [
            # ── Seismic ──
            'earthquake', 'quake struck', 'quake hit', 'strong earthquake',
            'powerful earthquake', 'major earthquake', 'magnitude earthquake',
            'earthquake magnitude', 'aftershock', 'aftershocks', 'seismic',
            'tremor', 'earthquake epicenter', 'earthquake epicentre',
            'earthquake death toll', 'quake death toll', 'earthquake survivors',
            'trapped under rubble', 'buildings collapsed',
            # ── Tsunami ──
            'tsunami', 'tsunami warning', 'tsunami alert', 'tsunami waves', 'tidal wave',
            # ── Flood ──
            'flooding', 'flash flood', 'flash floods', 'severe flooding',
            'catastrophic flooding', 'monsoon floods', 'flood waters', 'floodwaters',
            'deadly floods', 'record flooding', 'dam collapse', 'dam burst',
            'dam failure', 'levee breach', 'glacial lake outburst', 'inundation',
            # ── Tropical storm / cyclone ──
            'cyclone', 'tropical cyclone', 'hurricane', 'typhoon', 'super typhoon',
            'storm surge', 'tropical storm', 'made landfall',
            'category 4 hurricane', 'category 5 hurricane',
            'category 4 storm', 'category 5 storm',
            # ── Volcanic ──
            'volcanic eruption', 'volcano erupts', 'volcano erupted', 'volcanic ash',
            'ashfall', 'lava flow', 'pyroclastic', 'volcano alert',
            # ── Landslide / mudslide ──
            'landslide', 'landslides', 'mudslide', 'mudflow', 'rockslide', 'debris flow',
            # ── Wildfire ──
            'wildfire', 'wildfires', 'bushfire', 'forest fire', 'wildfire evacuations',
            # ── Drought declared as disaster ──
            'drought emergency', 'drought disaster', 'drought state of emergency',
            # ── Disaster-response framing ──
            'natural disaster', 'disaster zone', 'disaster declared',
            'state of emergency declared', 'state of disaster',
            'disaster relief', 'search and rescue operation', 'humanitarian disaster',
            'gdacs red alert', 'gdacs orange alert', 'red alert issued',
        ],
        'high_intensity_markers': [
            # Magnitude bands (major / great quakes)
            'magnitude 6', 'magnitude 7', 'magnitude 8', 'magnitude 9',
            # Confirmed catastrophic hazards
            'tsunami warning', 'tsunami alert', 'dam collapse', 'dam burst',
            'dam failure', 'category 4 hurricane', 'category 5 hurricane',
            'super typhoon', 'volcanic eruption', 'pyroclastic',
            # Human-toll language
            'thousands killed', 'hundreds killed', 'thousands displaced',
            'mass casualties', 'death toll rises', 'death toll climbs',
            'trapped under rubble', 'state of emergency declared', 'state of disaster',
            # USGS PAGER + GDACS alert escalation
            'pager orange', 'pager red', 'gdacs red alert', 'gdacs orange alert',
        ],
    },
}


# ============================================================
# COUNTRY + SUB-REGION EXTRACTION
# ============================================================
# v1.3.0 (May 19 2026) -- Expanded with sub-region patterns.
#
# Humanitarian journalism often uses specific place names rather than
# parent country names ("El Fasher siege" rather than "Sudan crisis";
# "Rakhine displacement" rather than "Myanmar crisis"). Without these
# sub-region patterns, we'd miss the most editorially-elevated coverage.
#
# Sub-regions are treated as separate "country codes" to preserve
# analytical granularity. Convergence math counts them as distinct
# signals — which is correct, since "Sudan AND Darfur AND El Fasher
# all firing" is meaningfully different signal than "Sudan firing".
#
# Word-boundary matching prevents collisions (e.g. 'niger' won't match
# 'nigerian' or 'nigeria' due to regex \b on both sides).

COUNTRY_PATTERNS = {
    # ─── AFRICA: heavy concentration of humanitarian risk ───
    # Egypt
    'egypt':            ['egypt', 'egyptian'],
    # Ethiopia + sub-regions (Tigray, Amhara, Afar -- active conflict zones)
    'ethiopia':         ['ethiopia', 'ethiopian'],
    'tigray':           ['tigray', 'tigrayan'],
    'amhara':           ['amhara'],
    'afar_region':      ['afar region', 'afar conflict'],
    # Sudan + sub-regions (Darfur is its own humanitarian universe)
    'sudan':            ['sudan', 'sudanese'],
    'darfur':           ['darfur', 'darfuri'],
    'el_fasher':        ['el fasher', 'el-fasher', 'al fashir', 'el fasher siege'],
    'khartoum':         ['khartoum'],
    'south_sudan':      ['south sudan'],
    # DRC + sub-regions (eastern conflict zones)
    'drc':              ['drc', 'democratic republic of the congo', 'eastern congo'],
    'north_kivu':       ['north kivu', 'goma', 'kivu province'],
    'south_kivu':       ['south kivu', 'bukavu'],
    'ituri':            ['ituri province', 'ituri district'],
    # Somalia + Horn of Africa specifics
    'somalia':          ['somalia', 'somali'],
    'somaliland':       ['somaliland'],
    'mogadishu':        ['mogadishu'],
    # Sahel + West Africa
    'kenya':            ['kenya', 'kenyan'],
    'nigeria':          ['nigeria', 'nigerian'],
    'borno_state':      ['borno state', 'maiduguri', 'lake chad basin'],
    'chad':             ['chad'],
    'niger':            ['niger', 'nigerien'],
    'mali':             ['mali', 'malian'],
    'burkina_faso':     ['burkina faso', 'burkinabe'],
    # Mozambique + Cabo Delgado (active insurgency)
    'mozambique':       ['mozambique', 'mozambican'],
    'cabo_delgado':     ['cabo delgado', 'palma mozambique'],
    # ─── v1.4.0 (May 23 2026) Africa health/displacement expansion ───
    # Uganda (Ebola history, largest refugee host in Africa, Marburg risk)
    'uganda':           ['uganda', 'ugandan'],
    'kampala':          ['kampala'],
    # Rwanda (Marburg outbreak 2024; refugees from DRC/Burundi)
    'rwanda':           ['rwanda', 'rwandan'],
    'kigali':           ['kigali'],
    # Burundi (RVF history, displacement, paired with DRC eastern story)
    'burundi':          ['burundi', 'burundian'],
    # Tanzania (Marburg risk; Lake Victoria basin)
    'tanzania':         ['tanzania', 'tanzanian'],
    # Central African Republic (chronic crisis, paired with DRC/Chad)
    'car':              ['central african republic',
                          'car humanitarian', 'central african'],
    'bangui':           ['bangui'],
    # Eritrea (humanitarian gap state; paired with Tigray story)
    'eritrea':          ['eritrea', 'eritrean'],
    # West Africa: Sahel coastal spillover + Ebola "home base" states
    'guinea':           ['guinea conakry', 'guinea republic',
                          'guinean republic', 'conakry'],
    'guinea_bissau':    ['guinea-bissau', 'guinea bissau', 'bissau'],
    'sierra_leone':     ['sierra leone', 'sierra leonean', 'freetown'],
    'liberia':          ['liberia', 'liberian', 'monrovia'],
    'cote_divoire':     ["cote d'ivoire", "cote d ivoire", "côte d'ivoire",
                          'ivory coast', 'ivorian', 'abidjan'],
    'ghana':            ['ghana', 'ghanaian', 'accra'],
    'benin':            ['benin', 'beninese'],
    'togo':             ['togo', 'togolese', 'lome'],
    'senegal':          ['senegal', 'senegalese', 'dakar'],
    'mauritania':       ['mauritania', 'mauritanian'],
    'gambia':           ['gambia', 'gambian'],
    'cameroon':         ['cameroon', 'cameroonian', 'yaounde', 'far north cameroon'],
    'gabon':            ['gabon', 'gabonese'],
    'congo_brazzaville':['republic of the congo', 'congo-brazzaville',
                          'congo brazzaville', 'brazzaville'],
    # Angola (refugee receiver from DRC; cholera history)
    'angola':           ['angola', 'angolan', 'luanda'],
    # Botswana (drought/food security exposure; commodities-tracked)
    'botswana':         ['botswana', 'gaborone'],
    # Namibia (climate vulnerability; refugee corridor)
    'namibia':          ['namibia', 'namibian'],
    # Lesotho (food security; SACU economic vulnerability)
    'lesotho':          ['lesotho'],
    # Eswatini (formerly Swaziland; food security)
    'eswatini':         ['eswatini', 'swaziland'],
    # Southern Africa (existing)
    'madagascar':       ['madagascar', 'malagasy'],
    'malawi':           ['malawi'],
    'zambia':           ['zambia'],
    'zimbabwe':         ['zimbabwe', 'zimbabwean'],
    'south_africa':     ['south africa', 'south african'],
    # North Africa
    'morocco':          ['morocco', 'moroccan'],
    'tunisia':          ['tunisia', 'tunisian'],
    'algeria':          ['algeria', 'algerian'],
    'libya':            ['libya', 'libyan'],

    # ─── ASIA: humanitarian gaps without Asifah trackers ───
    # Myanmar + sub-regions (Rakhine = Rohingya story; Karen + Shan = ethnic conflict)
    'myanmar':          ['myanmar', 'burma', 'burmese'],
    'rakhine':          ['rakhine state', 'rakhine', 'rohingya'],
    'karen_state':      ['karen state', 'karenni', 'kayah'],
    'shan_state':       ['shan state'],
    'kachin_state':     ['kachin state', 'kachin'],
    'sagaing':          ['sagaing region', 'sagaing'],
    # Bangladesh + Cox's Bazar (Rohingya refugee camps)
    'bangladesh':       ['bangladesh', 'bangladeshi'],
    'coxs_bazar':       ["cox's bazar", 'kutupalong'],
    # Sri Lanka, Afghanistan, Nepal, SE Asia
    'sri_lanka':        ['sri lanka', 'sri lankan'],
    'afghanistan':      ['afghanistan', 'afghan'],
    'kabul':            ['kabul'],
    'kandahar':         ['kandahar'],
    'nepal':            ['nepal', 'nepalese', 'nepali'],
    'vietnam':          ['vietnam', 'vietnamese'],
    'philippines':      ['philippines', 'filipino'],
    'indonesia':        ['indonesia', 'indonesian'],
    'thailand':         ['thailand', 'thai'],
    'laos':             ['laos', 'lao'],
    'cambodia':         ['cambodia', 'cambodian'],

    # ─── AMERICAS: humanitarian gaps without Asifah trackers ───
    'jamaica':          ['jamaica', 'jamaican'],
    # Haiti + sub-regions (capital + northern gang corridor)
    'haiti':            ['haiti', 'haitian'],
    'port_au_prince':   ['port-au-prince', 'port au prince'],
    'cap_haitien':      ['cap-haitien', 'cap haitien'],
    'el_salvador':      ['el salvador', 'salvadoran'],
    'honduras':         ['honduras', 'honduran'],
    'guatemala':        ['guatemala', 'guatemalan'],
    'nicaragua':        ['nicaragua', 'nicaraguan'],
    'argentina':        ['argentina', 'argentinian', 'argentine'],

    # ─── DISASTER-PRONE SWEEP (Jul 1 2026): seismic arcs, monsoon-flood belts,
    #     hurricane/cyclone tracks, and Ring-of-Fire volcanic zones. Many of these
    #     had NO country pattern, so their disaster + humanitarian articles were
    #     silently dropped at attribution (_extract_country_from_text). This closes
    #     that gap for ALL categories, not just natural_disaster. ───
    # -- Latin America + Caribbean (Andean/Caribbean seismic + Atlantic storms) --
    'venezuela':          ['venezuela', 'venezuelan'],
    'colombia':           ['colombia', 'colombian'],
    'mexico':             ['mexico', 'mexican'],
    'chile':              ['chile', 'chilean'],
    'peru':               ['peru', 'peruvian'],
    'ecuador':            ['ecuador', 'ecuadorian', 'ecuadorean'],
    'bolivia':            ['bolivia', 'bolivian'],
    'brazil':             ['brazil', 'brazilian'],
    'paraguay':           ['paraguay', 'paraguayan'],
    'uruguay':            ['uruguay', 'uruguayan'],
    'panama':             ['panama', 'panamanian'],
    'costa_rica':         ['costa rica', 'costa rican'],
    'dominican_republic': ['dominican republic'],
    'puerto_rico':        ['puerto rico', 'puerto rican'],
    'trinidad_tobago':    ['trinidad and tobago'],
    'dominica':           ['dominica'],
    'bahamas':            ['bahamas', 'bahamian'],
    # -- Europe / Mediterranean (Aegean-Anatolian seismic + Etna/Iceland volcanic) --
    'turkey':             ['turkey', 'turkish', 'turkiye', 'türkiye'],
    'greece':             ['greece', 'greek'],
    'italy':              ['italy', 'italian'],
    'iceland':            ['iceland', 'icelandic'],
    'portugal':           ['portugal', 'portuguese'],
    # -- South / Central Asia (Himalayan belt + monsoon floods) --
    'pakistan':           ['pakistan', 'pakistani'],
    'india':              ['india', 'indian'],
    # -- East Asia + Pacific (Ring of Fire, typhoon track) --
    'japan':              ['japan', 'japanese'],
    'china':              ['china', 'chinese'],
    'taiwan':             ['taiwan', 'taiwanese'],
    'south_korea':        ['south korea', 'south korean'],
    'papua_new_guinea':   ['papua new guinea'],
    'vanuatu':            ['vanuatu'],
    'fiji':               ['fiji', 'fijian'],
    'tonga':              ['tonga', 'tongan'],
    'solomon_islands':    ['solomon islands'],
    'new_zealand':        ['new zealand'],

    # ─── TRACKED COUNTRIES: listed so we can dedupe vs regional BLUFs ───
    # Note: These ARE captured in their own Asifah trackers — humanitarian
    # signals from these still fire here but are flagged is_tracked_country=True
    # for the convergence aggregator's downstream handling.
    # Gaza + sub-regions (each Gaza zone is a distinct humanitarian story)
    'gaza':             ['gaza', 'gaza strip'],
    'gaza_north':       ['northern gaza', 'gaza city', 'beit hanoun', 'jabaliya'],
    'khan_younis':      ['khan younis', 'khan yunis'],
    'rafah':            ['rafah'],
    # Lebanon + Bekaa (humanitarian zones outside the south)
    'lebanon':          ['lebanon', 'lebanese'],
    'bekaa_valley':     ['bekaa valley', 'bekaa'],
    # Syria
    'syria':            ['syria', 'syrian'],
    'aleppo':           ['aleppo'],
    'idlib':            ['idlib'],
    # Yemen + sub-regions (Hodeidah = port crisis; Sanaa = political; Aden = displacement)
    'yemen':            ['yemen', 'yemeni'],
    'hodeidah':         ['hodeidah', 'hudaydah', 'al hudaydah'],
    'sanaa':            ['sanaa', "sana'a", 'sana a'],
    'aden':             ['aden'],
    'saada':            ['saada', 'sa\'dah', 'sa dah'],
    # Iran, Cuba (already Asifah-tracked)
    'iran':             ['iran', 'iranian'],
    'cuba':             ['cuba', 'cuban'],
}

# Countries with full Asifah rhetoric/stability trackers (their humanitarian
# signals are flagged is_tracked_country=True downstream — they still count
# toward convergence aggregation but are also visible in their own BLUFs).
# Includes sub-regions of tracked countries (Khan Younis = tracked under Gaza).
TRACKED_COUNTRIES = {
    'lebanon', 'bekaa_valley',
    'syria', 'aleppo', 'idlib',
    'yemen', 'hodeidah', 'sanaa', 'aden', 'saada',
    'iran',
    'cuba',
    'gaza', 'gaza_north', 'khan_younis', 'rafah',
    # Disaster-prone countries that ALSO have full Asifah trackers (Jul 1 2026):
    # flagged so their disaster/humanitarian signals still count toward convergence
    # but are deprioritized vs genuinely novel (untracked) countries in the sort.
    'venezuela', 'turkey', 'china', 'taiwan', 'japan', 'india', 'pakistan',
    'chile', 'peru',
}

# Country-name length sort: match longest first to avoid sub-string collisions.
# Examples: 'south sudan' must match before 'sudan'; 'khan younis' before 'gaza';
# 'el fasher' before 'darfur'; 'cabo delgado' before 'mozambique'.
_COUNTRY_TOKENS_SORTED = []
for country_code, patterns in COUNTRY_PATTERNS.items():
    for pattern in patterns:
        _COUNTRY_TOKENS_SORTED.append((pattern, country_code))
_COUNTRY_TOKENS_SORTED.sort(key=lambda kv: -len(kv[0]))


# ============================================================
# SEVERITY SCORING
# ============================================================
SEVERITY_BASELINE = 1   # signal exists, low confidence
SEVERITY_MEDIUM   = 2   # signal + intensity language
SEVERITY_HIGH     = 3   # signal + high-intensity marker

# ─── Convergence thresholds ───
#
# v1.0 thresholds (April 2026): calibrated when detector read ONLY from ME
# tracker article pools (~80 articles per scan, mostly conflict-themed).
# At that scale, 6+ countries firing simultaneously was a genuinely rare
# signal worth elevating to L4 ACTIVE.
#
# v1.3 (May 2026): humanitarian_article_gatherer.py now feeds a much larger
# article pool (~300-800 articles per scan, drawn from ReliefWeb + UN agencies
# + GDELT humanitarian queries + Brave sub-region results). Plus 77 country/
# sub-region codes vs the old 46.
#
# EXPECTED POST-DEPLOY BEHAVIOR:
#   - countries_active will jump significantly (likely 8-15 per scan)
#   - categories_active will routinely hit 4+ (food + displacement + aid alone
#     fire daily across multiple countries)
#   - L4-L5 may become the default state rather than the exceptional one
#
# IF L5 GLOBAL fires on every scan after deploy, tune one of three ways:
#   (a) Raise CONVERGENCE_GLOBAL_MIN to 14-15 countries
#   (b) Change CONVERGENCE_CATEGORIES_FOR_GLOBAL from OR (4+ alone) to AND
#       (require BOTH 10+ countries AND 5+ categories simultaneously)
#   (c) Filter tracked-country signals out of convergence count so only
#       NOVEL countries (countries without their own Asifah tracker) drive
#       elevation — Sudan/Yemen/Gaza/Lebanon already have other surfaces
#
# Recommend observing 1-2 weeks of real data before tuning. The first
# scans will show what's actually firing vs theoretical expectations.

CONVERGENCE_FORMING_MIN  = 3   # 3-5 countries -> L3
CONVERGENCE_ACTIVE_MIN   = 6   # 6-9 countries -> L4
CONVERGENCE_GLOBAL_MIN   = 10  # 10+ countries -> L5
CONVERGENCE_CATEGORIES_FOR_GLOBAL = 4  # OR 4+ categories simultaneously -> L5


# ============================================================
# DETECTION FUNCTIONS
# ============================================================
def _scan_article_text(text, category_cfg):
    """
    Scan a piece of text against a category's keywords.
    Returns (matched, severity, matched_keywords).
    """
    if not text:
        return (False, 0, [])
    text_lower = text.lower()
    matches = [kw for kw in category_cfg['keywords'] if kw in text_lower]
    if not matches:
        return (False, 0, [])

    # Severity: high if any high-intensity marker present
    high_markers = category_cfg.get('high_intensity_markers', [])
    if any(m in text_lower for m in high_markers):
        return (True, SEVERITY_HIGH, matches)

    # Medium if 2+ keyword matches
    if len(matches) >= 2:
        return (True, SEVERITY_MEDIUM, matches)

    return (True, SEVERITY_BASELINE, matches)


def _extract_country_from_text(text):
    """
    Extract the most likely country mentioned in a piece of text.
    Returns canonical country code or None.

    Uses longest-pattern-first matching to avoid e.g. 'south sudan'
    being captured by 'sudan'.
    """
    if not text:
        return None
    text_lower = text.lower()
    for pattern, country_code in _COUNTRY_TOKENS_SORTED:
        # Use word-boundary check to avoid 'iran' matching 'transparent'
        if re.search(r'\b' + re.escape(pattern) + r'\b', text_lower):
            return country_code
    return None


def detect_humanitarian_signals(articles):
    """
    Main detection entry point.

    Takes a list of article dicts (each with 'title' + 'description' or 'text')
    and returns a list of detected signals.

    Each signal is a dict:
      {
        'category':         'food_price_crisis',
        'country':          'egypt',
        'severity':         1-3,
        'pressure_type':    'humanitarian',
        'level':            3-5 (mapped from severity),
        'short_text':       headline-style summary,
        'long_text':        2-3 sentence context,
        'source_url':       article URL,
        'source_title':     article title,
        'matched_keywords': [...],
        'detected_at':      ISO timestamp,
        'icon':             emoji,
      }
    """
    if not articles:
        return []

    detected = []
    seen_country_category = set()  # dedupe per country+category

    for art in articles:
        title = (art.get('title') or '').strip()
        desc  = (art.get('description') or art.get('snippet') or art.get('text') or '').strip()
        text  = f"{title} {desc}"
        if not text.strip():
            continue

        country = _extract_country_from_text(text)
        if not country:
            continue

        url = art.get('url') or art.get('link') or ''
        source = art.get('source') or art.get('source_name') or 'unknown'

        for cat_key, cat_cfg in SIGNAL_CATEGORIES.items():
            matched, severity, matched_kws = _scan_article_text(text, cat_cfg)
            if not matched:
                continue

            dedup_key = (country, cat_key)
            if dedup_key in seen_country_category:
                # Already captured this country+category — bump severity if higher
                for d in detected:
                    if d['country'] == country and d['category'] == cat_key:
                        if severity > d['severity']:
                            d['severity'] = severity
                            d['level'] = _severity_to_level(severity)
                            d['matched_keywords'].extend(matched_kws)
                        break
                continue

            seen_country_category.add(dedup_key)
            level = _severity_to_level(severity)
            country_label = country.replace('_', ' ').title()

            short_text = (
                f"{cat_cfg['icon']} {country_label}: {cat_cfg['label'].lower()} signal"
                f"{' (high intensity)' if severity == SEVERITY_HIGH else ''}"
            )
            long_text = (
                f"{country_label} showing {cat_cfg['label'].lower()} signals "
                f"(severity {severity}/3): {', '.join(matched_kws[:3])}. "
                f"Source: {source}. {cat_cfg['description']}."
            )

            detected.append({
                'category':         cat_key,
                'country':          country,
                'country_label':    country_label,
                'severity':         severity,
                'pressure_type':    'humanitarian',
                'level':            level,
                'short_text':       short_text[:150],
                'long_text':        long_text,
                'source_url':       url,
                'source_title':     title,
                'source':           source,
                'matched_keywords': list(set(matched_kws))[:5],
                'detected_at':      datetime.now(timezone.utc).isoformat(),
                'icon':             cat_cfg['icon'],
                'theatre':          'global_humanitarian',
                'region':           'global_humanitarian',
                'is_tracked_country': country in TRACKED_COUNTRIES,
            })

    return detected


def _severity_to_level(severity):
    """Map severity 1-3 to GPI level 0-5."""
    return {1: 3, 2: 4, 3: 5}.get(severity, 3)


# ── Acute single-event elevation (Jul 1 2026) ──
# Slow-burn categories (food / displacement / currency) are BREADTH-driven: many
# weak signals across many countries is the story, and the country-count tiers
# below are the right lens. ACUTE categories are the opposite -- one catastrophic
# earthquake, tsunami, or outbreak in a SINGLE country is a Global Pressure event
# on its own, and the breadth math alone would bury it at baseline (1 country).
# So a high-severity acute signal FLOORS the region level (single-event elevation);
# a COMPOUND event -- one signal spanning 2+ distinct hazard families, e.g.
# earthquake + tsunami -- or multiple simultaneous acute catastrophes floors it
# higher. This keeps the sensor honest: the dial should read high when a
# catastrophe actually happens, not only when several happen at once.
ACUTE_CATEGORIES = {'natural_disaster', 'health_emergency'}

_DISASTER_HAZARD_FAMILIES = {
    'seismic':   ('earthquake', 'quake', 'aftershock', 'seismic', 'magnitude', 'tremor'),
    'tsunami':   ('tsunami', 'tidal wave'),
    'flood':     ('flood', 'inundation', 'dam collapse', 'dam burst', 'dam failure', 'levee'),
    'storm':     ('cyclone', 'hurricane', 'typhoon', 'storm surge', 'tropical storm'),
    'volcanic':  ('volcano', 'volcanic', 'eruption', 'lava', 'ashfall', 'pyroclastic'),
    'landslide': ('landslide', 'mudslide', 'mudflow', 'rockslide', 'debris flow'),
    'wildfire':  ('wildfire', 'bushfire', 'forest fire'),
}

def _disaster_families(matched_keywords):
    """Return the set of distinct hazard families present in a signal's matched keywords.
    Two or more families in one signal (e.g. quake + tsunami) = a compound catastrophe."""
    joined = ' '.join(matched_keywords or []).lower()
    fams = set()
    for fam, toks in _DISASTER_HAZARD_FAMILIES.items():
        if any(tok in joined for tok in toks):
            fams.add(fam)
    return fams


# ============================================================
# CONVERGENCE AGGREGATION
# ============================================================
def aggregate_convergence(signals):
    """
    Aggregate detected signals into convergence assessment.

    Returns dict:
      {
        'tier':                'baseline' | 'forming' | 'active' | 'global',
        'max_level':           0-5,
        'level_label':         display string,
        'countries_active':    int,
        'categories_active':   int,
        'countries':           list of country codes with signals,
        'categories':          list of category keys with signals,
        'by_country':          dict {country_code: [signals]},
        'by_category':         dict {category_key: [signals]},
        'tracked_countries_present': bool,
        'novel_countries':     list of country codes NOT in TRACKED_COUNTRIES,
      }
    """
    if not signals:
        return {
            'tier':              'baseline',
            'max_level':         0,
            'level_label':       'BASELINE -- No humanitarian convergence signals',
            'countries_active':  0,
            'categories_active': 0,
            'countries':         [],
            'categories':        [],
            'by_country':        {},
            'by_category':       {},
            'tracked_countries_present': False,
            'novel_countries':   [],
        }

    countries_set  = set(s['country']  for s in signals)
    categories_set = set(s['category'] for s in signals)
    novel = [c for c in countries_set if c not in TRACKED_COUNTRIES]

    # Convergence tier — primarily based on UNIQUE COUNTRIES with active signals
    # (novel countries weighted more heavily since tracked-country signals would
    # already be flowing through their dedicated BLUFs)
    novel_count = len(novel)
    total_countries = len(countries_set)
    categories_count = len(categories_set)

    # Tier determination
    if total_countries >= CONVERGENCE_GLOBAL_MIN or categories_count >= CONVERGENCE_CATEGORIES_FOR_GLOBAL:
        tier = 'global'
        max_level = 5
        level_label = (
            f'GLOBAL CONVERGENCE -- {total_countries} countries × '
            f'{categories_count} crisis categories simultaneously active'
        )
    elif total_countries >= CONVERGENCE_ACTIVE_MIN:
        tier = 'active'
        max_level = 4
        level_label = (
            f'CONVERGENCE ACTIVE -- {total_countries} countries showing '
            f'distributed humanitarian distress signals'
        )
    elif total_countries >= CONVERGENCE_FORMING_MIN:
        tier = 'forming'
        max_level = 3
        level_label = (
            f'CONVERGENCE FORMING -- {total_countries} countries showing '
            f'humanitarian distress signals (watch for further spread)'
        )
    else:
        tier = 'baseline'
        max_level = 1 if signals else 0
        level_label = (
            f'BASELINE -- {total_countries} country with humanitarian signals '
            f'(below convergence threshold of {CONVERGENCE_FORMING_MIN})'
        )

    # ── Acute single-event elevation floor ──
    # A high-severity acute signal (catastrophic disaster / outbreak) elevates the
    # region regardless of how many OTHER countries are firing. Compound hazards
    # (quake + tsunami in one signal) or multiple simultaneous catastrophes floor
    # to global. This runs AFTER the breadth tier so it can only raise, never lower.
    acute_high = [s for s in signals
                  if s.get('category') in ACUTE_CATEGORIES
                  and s.get('severity', 0) >= SEVERITY_HIGH]
    if acute_high:
        compound = [s for s in acute_high
                    if len(_disaster_families(s.get('matched_keywords'))) >= 2]
        lead = acute_high[0]
        lead_country = lead.get('country_label') or lead.get('country', '').replace('_', ' ').title()
        lead_cat = SIGNAL_CATEGORIES.get(lead.get('category'), {}).get('label', lead.get('category', 'disaster'))
        if compound:
            acute_floor, fams = 5, ', '.join(sorted(_disaster_families(compound[0].get('matched_keywords'))))
            acute_label = (f'ACUTE COMPOUND DISASTER -- {lead_country}: converging hazards ({fams}) '
                           f'present in the same event; single-event elevation')
        elif len(acute_high) >= 2:
            acute_floor = 5
            acute_label = (f'ACUTE MULTI-EVENT -- {len(acute_high)} catastrophic disaster/outbreak '
                           f'signals active simultaneously; single-event elevation')
        else:
            acute_floor = 4
            acute_label = (f'ACUTE EVENT -- catastrophic {lead_cat.lower()} signal in {lead_country}; '
                           f'single-event elevation above the breadth threshold')
        if acute_floor > max_level:
            max_level, tier, level_label = acute_floor, 'acute', acute_label

    # Group signals by country + category
    by_country = {}
    by_category = {}
    for s in signals:
        by_country.setdefault(s['country'], []).append(s)
        by_category.setdefault(s['category'], []).append(s)

    return {
        'tier':              tier,
        'max_level':         max_level,
        'level_label':       level_label,
        'countries_active':  total_countries,
        'categories_active': categories_count,
        'countries':         sorted(countries_set),
        'categories':        sorted(categories_set),
        'by_country':        by_country,
        'by_category':       by_category,
        'tracked_countries_present': any(c in TRACKED_COUNTRIES for c in countries_set),
        'novel_countries':   sorted(novel),
    }


# ============================================================
# BLUF-SHAPED PAYLOAD BUILDER (consumed by GPI)
# ============================================================
def build_humanitarian_bluf(signals, aggregation=None):
    """
    Build a BLUF-shaped payload that GPI consumes via REGIONAL_BLUF_ENDPOINTS.

    Structure mirrors me_regional_bluf.py output so GPI's existing logic
    iterates this as the 5th 'region' (global_humanitarian) with zero
    GPI-side code changes (just add to REGIONAL_BLUF_ENDPOINTS dict).

    Returns dict matching the canonical BLUF schema:
      {
        'region':              'global_humanitarian',
        'max_level':           0-5,
        'peak_level':          0-5,
        'posture_label':       display string,
        'posture_color':       hex,
        'top_signals':         list of canonical signal dicts (capped at 5),
        'signals':             list of all signals (full pool for axis aggregation),
        'updated_at':          ISO,
        'meta':                {countries_active, categories_active, tier, ...}
      }
    """
    if aggregation is None:
        aggregation = aggregate_convergence(signals or [])

    tier = aggregation['tier']
    max_level = aggregation['max_level']
    posture_label = aggregation['level_label']

    # Color per tier (matches GPI canonical scheme)
    posture_color = {
        'baseline': '#6b7280',
        'forming':  '#f59e0b',
        'active':   '#f97316',
        'global':   '#dc2626',
        'acute':    '#dc2626',   # single catastrophic disaster / outbreak
    }.get(tier, '#6b7280')

    # Build canonical signal payload — sorted by severity desc, novel-first
    sorted_signals = sorted(
        signals or [],
        key=lambda s: (
            -s.get('severity', 0),
            0 if not s.get('is_tracked_country') else 1,  # novel countries first
            -s.get('level', 0),
        ),
    )

    canonical_signals = []
    for s in sorted_signals:
        canonical_signals.append({
            'category':      s['category'],
            'country':       s['country'],
            'theatre':       'global_humanitarian',
            'region':        'global_humanitarian',
            'level':         s['level'],
            'pressure_type': 'humanitarian',
            'icon':          s['icon'],
            'color':         posture_color,
            'short_text':    s['short_text'],
            'long_text':     s['long_text'],
            'priority':      s['severity'] * 3,  # rough priority for GPI sort tiebreaker
            'source_url':    s.get('source_url', ''),
            'source':        s.get('source', ''),
        })

    return {
        'region':         'global_humanitarian',
        'max_level':      max_level,
        'peak_level':     max_level,
        'posture_label':  posture_label,
        'posture_color':  posture_color,
        'top_signals':    canonical_signals[:5],
        'signals':        canonical_signals,
        'updated_at':     datetime.now(timezone.utc).isoformat(),
        'meta': {
            'tier':                tier,
            'countries_active':    aggregation['countries_active'],
            'categories_active':   aggregation['categories_active'],
            'countries':           aggregation['countries'],
            'categories':          aggregation['categories'],
            'novel_countries':     aggregation['novel_countries'],
            'tracked_countries_present': aggregation['tracked_countries_present'],
            'detector_version':    f'humanitarian_convergence_detector v{__version__}',
        },
    }


# ============================================================
# TOP-LEVEL ENTRY POINT
# ============================================================
def _surge_severity(yoy):
    """Severity 0-3 from a UNHCR YoY delta. 0 = not a surge (absence stays honest).
    The STOCK is never a signal; only the year-over-year SURGE is."""
    if not isinstance(yoy, dict):
        return 0
    delta = yoy.get('delta') or 0
    if delta <= 0:
        return 0  # flat or declining -> not a surge
    prior = yoy.get('prior_total') or 0
    pct = yoy.get('pct_change')
    if prior == 0:
        # appearing from ~zero -> notable only if large absolute (avoid coverage-onset noise)
        if delta >= 50000:
            return 2
        if delta >= 20000:
            return 1
        return 0
    if delta >= 50000 and pct is not None and pct >= 25:
        return 3
    if delta >= 20000 and pct is not None and pct >= 25:
        return 2
    if delta >= 10000 and pct is not None and pct >= 15:
        return 1
    return 0


def detect_unhcr_displacement_signals(unhcr_payload):
    """
    Build synthetic displacement_surge signals from UNHCR structured YoY deltas
    (the unhcr:all:latest payload written by unhcr_feeds.py).

    Each country is checked in BOTH directions:
      - hosted.yoy     -> absorbing a displacement wave (inbound)
      - originated.yoy -> generating displacement (outbound / internal crisis)
    Signals carry is_tracked_country so the aggregator de-weights countries that
    already have their own Asifah tracker (rhetoric pages take priority).
    Returns [] when nothing surges -- silence is a valid analytical output.
    """
    if not isinstance(unhcr_payload, dict):
        return []
    by_country = unhcr_payload.get('by_country') or {}
    if not isinstance(by_country, dict):
        return []

    signals = []
    now = datetime.now(timezone.utc).isoformat()

    for cid, cdata in by_country.items():
        if not isinstance(cdata, dict):
            continue
        hosted = cdata.get('hosted') or {}
        originated = cdata.get('originated') or {}
        h_yoy = hosted.get('yoy') if isinstance(hosted, dict) else None
        o_yoy = originated.get('yoy') if isinstance(originated, dict) else None

        h_sev = _surge_severity(h_yoy)
        o_sev = _surge_severity(o_yoy)
        if h_sev == 0 and o_sev == 0:
            continue

        if h_sev >= o_sev:
            sev, yoy, direction = h_sev, h_yoy, 'inbound'
        else:
            sev, yoy, direction = o_sev, o_yoy, 'outbound'

        label = cid.replace('_', ' ').title()
        delta = yoy.get('delta', 0)
        pct = yoy.get('pct_change')
        pct_txt = f" (+{pct}%)" if pct is not None else ""
        cur_year = yoy.get('current_year')

        if direction == 'inbound':
            short_text = f"\U0001f6b6 {label}: inbound displacement surge -- refugees/asylum +{delta:,} YoY{pct_txt}"
            long_text = (f"{label} hosted refugee/asylum population rose by {delta:,}{pct_txt} "
                         f"year-over-year (UNHCR end-{cur_year}). Consistent with absorbing a "
                         f"cross-border displacement wave.")
        else:
            short_text = f"\U0001f6b6 {label}: outbound displacement surge -- +{delta:,} displaced abroad YoY{pct_txt}"
            long_text = (f"Displacement originating from {label} rose by {delta:,}{pct_txt} "
                         f"year-over-year (UNHCR end-{cur_year}). Consistent with an intensifying "
                         f"internal crisis.")

        signals.append({
            'category':           'displacement_surge',
            'country':            cid,
            'country_label':      label,
            'severity':           sev,
            'pressure_type':      'humanitarian',
            'level':              _severity_to_level(sev),
            'short_text':         short_text[:150],
            'long_text':          long_text,
            'source_url':         'https://www.unhcr.org/refugee-statistics/',
            'source_title':       'UNHCR Refugee Data Finder (YoY displacement delta)',
            'source':             'UNHCR Refugee Data Finder',
            'matched_keywords':   ['unhcr_yoy_surge', direction],
            'detected_at':        now,
            'icon':               '\U0001f6b6',
            'theatre':            'global_humanitarian',
            'region':             'global_humanitarian',
            'is_tracked_country': cid in TRACKED_COUNTRIES,
            'signal_origin':      'unhcr_structured',
        })

    return signals


# ISO3 codes for countries that already have their own Asifah tracker.
# Mirrors TRACKED_COUNTRIES (which uses lowercase slugs); the World Bank payload
# keys on ISO3. Used to DE-WEIGHT tracked countries, not exclude them.
_WB_TRACKED_ISO3 = {'LBN', 'SYR', 'YEM', 'IRN', 'CUB', 'PSE'}

# Metrics that are structurally-normal-extreme for whole classes of economy and
# therefore must NOT fire a convergence signal on their own:
#   water_stress    -- permanent baseline of desalination / desert economies
#                      (Gulf states, Israel, North Africa, Central Asia).
#   reserves_months -- near-meaningless for currency-union / financial-hub
#                      members that do not hold large FX reserves (eurozone).
#   food_import_dependence -- a fragility (how hard a shock lands), not distress;
#                      every small island imports food. Exposure, not crisis.
# They count only as AMPLIFIERS inside a genuine compound cluster, never as a
# standalone alarm. (Absence stays honest: the raw readings still surface in the
# gatherer's sensor-layer output; we simply do not let them alone trigger an
# analyst-layer convergence read.)
_WB_AMPLIFIER_ONLY = {'water_stress', 'reserves_months', 'food_import_dependence'}

# Single-metric naming for lone-extreme survivors (a non-amplifier metric at an
# extreme reading). Each names the pathway + the named outcome it has
# historically preceded -- estimative voice, reader completes the inference.
_WB_SINGLE_LABEL = {
    'inflation': ('acute price instability',
        'runaway consumer prices have historically preceded subsidy-cut unrest and currency crises'),
    'food_insecurity': ('acute food insecurity',
        'food insecurity at this share of population has historically preceded subsistence-driven displacement'),
    'unemployment': ('labor-market distress',
        'extreme joblessness has historically preceded protest waves and out-migration pressure'),
    'poverty': ('deep structural poverty',
        'extreme-poverty headcounts at this level mark acute vulnerability to any further shock'),
    'food_import_dependence': ('import-dependence exposure',
        'heavy food-import reliance has historically preceded price-shock vulnerability when trade or financing is disrupted'),
}


def _wb_name_mechanism(stressed, extreme):
    """
    Map a cluster of co-occurring World Bank stressors to a NAMED structural
    mechanism + the named outcome it has historically preceded. Synthesis, not
    enumeration: names the pathway the instruments agree on. Returns
    (mechanism_label, precedent_clause). Precedent is precedent-anchored and
    estimative -- it never asserts an outcome.
    """
    s = set(stressed)
    ext = set(extreme)
    n = len(stressed)
    # Compound syndromes, most-specific first.
    if ('inflation' in ext) and ('food_insecurity' in s):
        return ('hyperinflation-famine coupling',
                'the coupling of runaway prices with broad food insecurity has historically '
                'preceded acute hunger crises and subsistence-driven unrest')
    if ('food_insecurity' in s) and ('water_stress' in s) and (('poverty' in s) or ('food_import_dependence' in s)):
        return ('subsistence-failure chain',
                'water-constrained domestic production layered on import dependence and poverty '
                'has historically preceded famine conditions')
    if ('inflation' in s) and ('food_import_dependence' in s):
        return ('balance-of-payments squeeze',
                'high inflation alongside heavy import dependence has historically preceded '
                'balance-of-payments crises and subsidy-cut unrest')
    if ('unemployment' in ext) and (('poverty' in s) or ('food_insecurity' in s)):
        return ('labor-market and welfare distress',
                'extreme joblessness alongside material deprivation has historically preceded '
                'protest waves and out-migration pressure')
    # Lone-extreme survivor: name it after its driving metric.
    if n == 1:
        for k in ('inflation', 'food_insecurity', 'unemployment', 'poverty', 'food_import_dependence'):
            if k in ext:
                return _WB_SINGLE_LABEL[k]
    # Genuine 2+ cluster with no named syndrome match.
    return ('compound structural stress',
            'the accumulation of co-occurring subsistence-cost and external-financing pressure '
            'has historically preceded periods of acute instability')


def detect_worldbank_structural_signals(wb_payload):
    """
    Build structural_stress signals from the World Bank gatherer payload
    (worldbank:structural:latest written by world_bank_gatherer.py).

    Sensor -> analyst handoff: the gatherer reports raw structural readings;
    THIS function applies the estimative interpretation. v1.6.1 calibration:
      * A signal needs at least one NON-amplifier stressor (inflation, food
        insecurity, unemployment, poverty, import dependence). A lone extreme on
        water stress or reserve-months is structurally-normal for desert /
        currency-union economies and is suppressed -- it amplifies, never fires.
      * A lone non-amplifier stressor fires only if it is EXTREME, and is capped
        at L4 -- L5 is reserved for genuine multi-system compound convergence.
      * Each surviving signal is named: the mechanism + the outcome it has
        historically preceded (synthesis, not a count).
    Returns [] when nothing converges (silence is a valid analytical output).
    """
    if not isinstance(wb_payload, dict):
        return []
    by_country = wb_payload.get('by_country') or {}
    if not isinstance(by_country, dict):
        return []

    signals = []
    now = datetime.now(timezone.utc).isoformat()

    for iso3, c in by_country.items():
        if not isinstance(c, dict):
            continue
        stressed = c.get('stressed') or []
        extreme = c.get('extreme') or []

        # --- Calibration gate ---
        non_amp_stressed = [k for k in stressed if k not in _WB_AMPLIFIER_ONLY]
        non_amp_extreme = [k for k in extreme if k not in _WB_AMPLIFIER_ONLY]
        # Need a genuine (non-amplifier) stressor: drops Gulf water-only and
        # eurozone reserves-only false positives.
        if not non_amp_stressed:
            continue
        # A lone genuine stressor must be extreme to fire; 2+ fire regardless.
        if len(stressed) < 2 and not non_amp_extreme:
            continue

        severity = max(1, min(3, int(c.get('stress_severity') or 1)))
        n = len(stressed)
        # Exposure is not distress: L5 (severity 3) requires genuine multi-system
        # convergence -- a non-amplifier (distress-metric) extreme, OR 3+ co-
        # occurring stressors. A lone amplifier extreme (desert water, thin
        # reserves, import reliance) caps at L4, never L5.
        if severity >= 3 and not (non_amp_extreme or n >= 3):
            severity = 2
        # A lone stressor never exceeds L4.
        if n < 2:
            severity = min(severity, 2)

        label = c.get('country_name', iso3)
        readings = c.get('indicators') or {}

        bits = []
        for key in stressed[:4]:
            r = readings.get(key) or {}
            if not r:
                continue
            trend = ''
            if r.get('deteriorating'):
                trend = ' rising' if r.get('stress_when') == 'above' else ' falling'
            bits.append(f"{r.get('label')} {r.get('value')}{r.get('unit', '')}{trend}")
        stressor_txt = '; '.join(bits) if bits else f"{len(stressed)} structural stressors"

        mechanism, precedent = _wb_name_mechanism(stressed, extreme)
        if n >= 2:
            lead = f"{label} shows {n} co-occurring structural stressors"
            if extreme:
                lead += ' (one at an extreme reading)'
        else:
            lead = f"{label} shows an extreme single-metric reading"

        short_text = f"\U0001f3e6 {label}: {mechanism} -- {stressor_txt}"
        long_text = (
            f"{lead}: {stressor_txt}. Signature: {mechanism} -- {precedent}. "
            f"(World Bank Indicators, latest available year per metric. Convergence "
            f"reading -- instruments agreeing, not a forecast.)"
        )

        signals.append({
            'category':           'structural_stress',
            'country':            iso3.lower(),
            'country_label':      label,
            'severity':           severity,
            'pressure_type':      'humanitarian',
            'level':              _severity_to_level(severity),
            'short_text':         short_text[:150],
            'long_text':          long_text,
            'mechanism':          mechanism,
            'source_url':         'https://data.worldbank.org',
            'source_title':       'World Bank Indicators (structural-stress sweep)',
            'source':             'World Bank Indicators API',
            'matched_keywords':   ['worldbank_structural', mechanism.replace(' ', '_')] + list(stressed[:4]),
            'detected_at':        now,
            'icon':               '\U0001f3e6',
            'theatre':            'global_humanitarian',
            'region':             'global_humanitarian',
            'is_tracked_country': iso3 in _WB_TRACKED_ISO3,
            'signal_origin':      'worldbank_structural',
        })

    return signals


def detect_and_build_bluf(articles, extra_signals=None):
    """
    Convenience wrapper: run detection + aggregation + build BLUF.
    Returns the canonical BLUF payload ready for the API endpoint.
    extra_signals: pre-built signals (e.g. UNHCR structured surges) merged in.
    """
    signals = detect_humanitarian_signals(articles or [])
    if extra_signals:
        signals = signals + list(extra_signals)
    aggregation = aggregate_convergence(signals)
    return build_humanitarian_bluf(signals, aggregation)


# ============================================================
# FLASK ROUTE REGISTRATION
# ============================================================
# Canonical Asifah pattern: each module exposes `register_X_routes(app)` so
# the app.py registration zone stays uncluttered. Reads articles from
# existing ME rhetoric tracker Redis caches — zero new API calls.

def register_humanitarian_convergence_routes(app, redis_client=None, json_module=None):
    """
    Register humanitarian convergence endpoints on the Flask app.

    v1.1.0 (May 19 2026) — REDIS PATTERN FIX
    Previous version expected redis-py client object (r.get/r.setex method
    interface). Asifah platform uses Upstash REST API directly across all
    rhetoric trackers + GPI + butterfly_reader. This created an architectural
    mismatch where the detector silently returned zero articles regardless
    of whether trackers had cached data.
    
    Fix: use the same Upstash REST pattern as rhetoric_tracker_iran.py and
    siblings. No app.py changes required.
    """
    from flask import jsonify

    # Use standard json if not provided
    _json = json_module
    if _json is None:
        import json as _json

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
            print(f'[humanitarian_convergence] Upstash GET error ({key}): {str(e)[:80]}')
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
            print(f'[humanitarian_convergence] Upstash SET error ({key}): {str(e)[:80]}')
            return False

    def _gather_articles():
        """
        Pull article pool for humanitarian detection.

        v1.2.0 (May 19 2026) -- DUAL-SOURCE STRATEGY
        Reads from TWO sources and combines:

          1. PRIMARY: humanitarian:articles:latest (written by humanitarian_article_gatherer.py
             every 12h). This is the dedicated humanitarian article pool with ReliefWeb,
             UN agencies, NGOs, GDELT humanitarian queries, and Brave sub-region results.

          2. SECONDARY: ME rhetoric tracker caches (rhetoric:iran:latest etc.). These
             provide context for tracked countries (Lebanon, Yemen, Syria, etc.) where
             humanitarian language may appear in conflict-context articles.

        Both sources are deduplicated by URL. Falls back gracefully if either is missing.
        """
        articles = []
        seen_urls = set()

        def _add_article(art):
            """Add article if not duplicate. Returns True if added."""
            if not isinstance(art, dict):
                return False
            url = art.get('url') or art.get('link') or ''
            if url and url in seen_urls:
                return False
            if url:
                seen_urls.add(url)
            articles.append(art)
            return True

        # ── SOURCE 1: Dedicated humanitarian gatherer pool (primary) ──
        gatherer_count = 0
        try:
            pool = _upstash_get('humanitarian:articles:latest')
            if isinstance(pool, dict):
                pool_articles = pool.get('articles', []) or []
                if isinstance(pool_articles, list):
                    for art in pool_articles:
                        if _add_article(art):
                            gatherer_count += 1
                    print(f'[humanitarian_convergence] Gathered {gatherer_count} articles '
                          f'from humanitarian:articles:latest (gatherer pool)')
                else:
                    print('[humanitarian_convergence] Gatherer pool malformed (articles not a list)')
            else:
                print('[humanitarian_convergence] humanitarian:articles:latest not yet populated '
                      '(gatherer may not have run yet) -- falling back to ME tracker pools only')
        except Exception as e:
            print(f'[humanitarian_convergence] Gatherer read error: {str(e)[:80]}')

        # ── SOURCE 2: ME rhetoric tracker caches (secondary, for tracked-country context) ──
        rhetoric_keys = [
            'rhetoric:iran:latest',
            'rhetoric:israel:latest',
            'rhetoric:lebanon:latest',
            'rhetoric:syria:latest',
            'rhetoric:yemen:latest',
            'rhetoric:iraq:latest',
            'rhetoric:oman:latest',
        ]
        me_tracker_count = 0
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
                        if _add_article(art):
                            me_tracker_count += 1
            except Exception as e:
                print(f'[humanitarian_convergence] Skipping {key}: {str(e)[:80]}')
                continue
        print(f'[humanitarian_convergence] Added {me_tracker_count} articles from {len(rhetoric_keys)} '
              f'ME tracker caches (secondary source)')

        print(f'[humanitarian_convergence] TOTAL: {len(articles)} articles '
              f'(gatherer={gatherer_count}, me_trackers={me_tracker_count})')
        return articles

    # ────────────────────────────────────────────────────────────
    # GET /api/humanitarian-convergence/bluf
    # ────────────────────────────────────────────────────────────
    @app.route('/api/humanitarian-convergence/bluf', methods=['GET'])
    def humanitarian_convergence_bluf():
        """
        BLUF-shaped payload consumed by GPI.

        v2.3 — Aggregates humanitarian signals from countries WITHOUT
        dedicated Asifah trackers (Egypt, Ethiopia, Myanmar, Sri Lanka,
        Jamaica, etc.) into a single convergence assessment that flows
        into GPI's humanitarian axis.

        Query param: ?force=true bypasses 30-min cache and forces fresh
        scan (canonical Asifah tracker convention).
        """
        from flask import request
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        try:
            # Try cached BLUF first (30-min TTL) — unless force=true
            if not force:
                cached = _upstash_get('humanitarian_convergence:bluf:latest')
                if cached and isinstance(cached, dict):
                    return jsonify(cached), 200

            # Build fresh
            articles = _gather_articles()
            # UNHCR structured displacement surges (shared Redis; gated by TRACKED_COUNTRIES)
            unhcr_signals = []
            try:
                _unhcr_all = _upstash_get('unhcr:all:latest')
                if isinstance(_unhcr_all, dict):
                    unhcr_signals = detect_unhcr_displacement_signals(_unhcr_all)
            except Exception as _ue:
                print(f'[humanitarian_convergence] UNHCR signal read skipped: {str(_ue)[:80]}')
            # World Bank structural-stress sweep (shared Redis; de-weighted by tracked set)
            wb_signals = []
            try:
                _wb_struct = _upstash_get('worldbank:structural:latest')
                if isinstance(_wb_struct, dict):
                    wb_signals = detect_worldbank_structural_signals(_wb_struct)
            except Exception as _we:
                print(f'[humanitarian_convergence] World Bank signal read skipped: {str(_we)[:80]}')
            bluf = detect_and_build_bluf(articles, extra_signals=unhcr_signals + wb_signals)

            # Cache for 30 min
            _upstash_setex('humanitarian_convergence:bluf:latest', 1800, bluf)

            return jsonify(bluf), 200

        except Exception as e:
            print(f'[humanitarian_convergence] error: {e}')
            # Return empty BLUF (HTTP 200) so GPI treats it as baseline
            return jsonify({
                'region':         'global_humanitarian',
                'max_level':      0,
                'peak_level':     0,
                'posture_label':  'OFFLINE -- detector error',
                'posture_color':  '#6b7280',
                'top_signals':    [],
                'signals':        [],
                'updated_at':     datetime.now(timezone.utc).isoformat(),
                'meta': {'tier': 'baseline', 'error': str(e)[:120]},
            }), 200

    # ────────────────────────────────────────────────────────────
    # GET /api/humanitarian-convergence/details
    # ────────────────────────────────────────────────────────────
    @app.route('/api/humanitarian-convergence/details', methods=['GET'])
    def humanitarian_convergence_details():
        """
        Full aggregation details (by_country, by_category, novel countries).
        Useful for frontend drill-down cards.
        """
        try:
            articles = _gather_articles()
            signals = detect_humanitarian_signals(articles)
            try:
                _unhcr_all = _upstash_get('unhcr:all:latest')
                if isinstance(_unhcr_all, dict):
                    signals = signals + detect_unhcr_displacement_signals(_unhcr_all)
            except Exception:
                pass
            try:
                _wb_struct = _upstash_get('worldbank:structural:latest')
                if isinstance(_wb_struct, dict):
                    signals = signals + detect_worldbank_structural_signals(_wb_struct)
            except Exception:
                pass
            agg = aggregate_convergence(signals)
            bluf = build_humanitarian_bluf(signals, agg)
            return jsonify({
                'bluf':           bluf,
                'aggregation':    agg,
                'signal_count':   len(signals),
                'article_count':  len(articles),
                'detector_version': __version__,
                'updated_at':     datetime.now(timezone.utc).isoformat(),
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)[:200]}), 500

    # ────────────────────────────────────────────────────────────
    # GET /api/humanitarian-convergence/health
    # ────────────────────────────────────────────────────────────
    @app.route('/api/humanitarian-convergence/health', methods=['GET'])
    def humanitarian_convergence_health():
        return jsonify({
            'module':           __module_id__,
            'version':          __version__,
            'signal_categories': list(SIGNAL_CATEGORIES.keys()),
            'category_count':   len(SIGNAL_CATEGORIES),
            'countries_tracked': len(COUNTRY_PATTERNS),
            'status':           'operational',
        }), 200

    print('[Humanitarian Convergence] Routes registered: /api/humanitarian-convergence/bluf, /details, /health')


# ============================================================
# MODULE METADATA
# ============================================================
__version__ = '1.7.0'
__module_id__ = 'humanitarian_convergence_detector'
print(f'[Humanitarian Convergence Detector] Module loaded -- v{__version__}')
