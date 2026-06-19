"""
fews_net.py
Asifah Analytics -- Shared Humanitarian Data Module (ME backend)
v1.1.0 -- June 19, 2026  (transcribed from the June 2026 FAOB, page-3/4 table)
  v1.0.0 -- initial scaffold (headliners from FAO-WFP; superseded)

CANONICAL FEWS NET FOOD-SECURITY LAYER
======================================
Single source of truth for IPC / Population-in-Need (PIN) food-security data,
transcribed directly from FEWS NET's June 2026 Food Assistance Outlook Brief
(FAOB). DATA + ACCESSORS only -- no scraping, no Flask state -- so every
consumer imports it cleanly:

  - syria_humanitarian.py  -> get_panel('syria') for the Food Security card
  - africa stability pages  -> get_panel(<code>)
  - humanitarian_convergence_detector.py -> famine_risk_countries() +
    high_severity_countries() to SEED the convergence (news then amplifies)

WHY A SHARED MODULE (not inside syria_humanitarian.py): FEWS NET is global;
embedding it in one country's module would force every other consumer to import
that country. Mirrors convergence_registry.py: one dataset, many readers.

DATA MODEL (per the FAOB methodology):
  - current_pin  : CURRENT PIN band (June 2026)
  - projected_pin: PROJECTED PIN band (December 2026, 7 months out)
  - pct_population: projected Dec 2026 PIN as approx % of total population
  - highest_ipc_phase: highest projected area-level IPC classification (MOST
    LIKELY outcome, after planned assistance). 1=Minimal..5=Famine.
  - risk_of_famine: FEWS NET's credible-ALTERNATIVE-scenario flag. Famine
    (Phase 5) is plausible but NOT the most-likely area outcome. Stored
    SEPARATELY from highest_ipc_phase, per FEWS NET methodology.
  - assistance_dependent: the FAOB "!" marker (e.g. "Crisis! (IPC Phase 3!)") --
    area would likely be at least one phase WORSE without current/planned aid.
  - trend_vs_last_year / trend_vs_5yr: Higher | Similar | Lower (* = approximate)
  - key_shocks: the FAOB "Key Shocks" column, verbatim.
  - compound_drivers: cross-cutting drivers the FAOB prose explicitly names that
    link to Asifah's commodity convergences (el_nino, middle_east_fertilizer).

DATA HONESTY: every record carries source / source_url / source_as_of. The 26
countries in the FAOB detail table are fully populated; remaining presence
countries (Gaza, Iran, Iraq, Ukraine, Pakistan, etc.) are listed in
PRESENCE_COUNTRIES but intentionally NOT given invented numbers.

CADENCE: refresh each FAOB cycle (~monthly). Bump META + as_of, update bands.
"""

# ============================================================
# MODULE METADATA  (June 2026 FAOB, page 1-2 key messages)
# ============================================================
META = {
    'cycle':         'June 2026',
    'projection_for':'December 2026',
    'source':        'FEWS NET Food Assistance Outlook Brief (FAOB), June 2026',
    'source_url':    'https://fews.net/global/food-assistance-outlook-brief/june-2026',
    'data_as_of':    '2026-06',
    'global_pin':    '115-125 million',     # projected Dec 2026 across presence countries
    'global_pct':    '12% of the population',
    'global_trend':  'Higher than Dec 2025 and higher than the five-year average',
    'compound_note': ('Iran-war Hormuz fuel/fertilizer squeeze and a 2026-2027 El Nino are '
                      'compounding drivers the FAOB names directly for Sahel and Southern Africa.'),
    'disclaimer':    ('PIN/IPC are projections of need, not forecasts of famine. risk_of_famine '
                      'flags a credible alternative scenario, not the most-likely outcome.'),
}

IPC_PHASES = {1: 'Minimal', 2: 'Stressed', 3: 'Crisis', 4: 'Emergency', 5: 'Famine'}

# ============================================================
# COUNTRY RECORDS -- the 26 countries in the June 2026 FAOB detail table
# (ordered by projected Dec 2026 PIN, descending, as in the brief)
# ============================================================
FEWS_COUNTRIES = {

    'sudan': {
        'name': 'Sudan', 'region': 'east_africa',
        'current_pin': '21.0-21.99M', 'current_pin_numeric': 21_500_000,
        'projected_pin': '20.0-20.99M', 'projected_pin_numeric': 20_500_000,
        'pct_population': '40-45%',
        'highest_ipc_phase': 4, 'risk_of_famine': True, 'assistance_dependent': False,
        'famine_risk_areas': ('Catastrophe (Phase 5) likely in NW North Darfur and parts of South '
                              'Kordofan (Dilling, western Nuba Mountains, Kadugli, around El-Obeid); '
                              'credible risk of Famine if besiegement worsens'),
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['conflict', 'economy'], 'compound_drivers': [],
        'notes': ('Largest crisis in the dataset. Emergency (Phase 4) widespread in North Darfur, '
                  'Greater Kordofan, Blue Nile after four years of war; harvests give slight Dec relief.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/east-africa/sudan',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'drc': {
        'name': 'Democratic Republic of the Congo', 'region': 'southern_africa',
        'current_pin': '16.0-16.99M', 'current_pin_numeric': 16_500_000,
        'projected_pin': '17.0-17.99M', 'projected_pin_numeric': 17_500_000,
        'pct_population': '10-15%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Higher*',
        'key_shocks': ['conflict', 'weather'], 'compound_drivers': [],
        'health_overlay': ('Ebola outbreak (since May 2026): epicenter Ituri, plus North/South Kivu. '
                           'Rwanda-Uganda border closures disrupting trade. Dec impact depends on epidemic '
                           'and border-closure duration.'),
        'notes': ('Crisis (Phase 3) persists in conflict areas, worst-affected households in Emergency '
                  '(Phase 4). Cross-references the cobalt-DRC commodity layer.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/southern-africa/democratic-republic-congo',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'nigeria': {
        'name': 'Nigeria', 'region': 'west_africa',
        'current_pin': '16.0-16.99M', 'current_pin_numeric': 16_500_000,
        'projected_pin': '16.0-16.99M', 'projected_pin_numeric': 16_500_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 4, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Higher', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['conflict', 'economy'], 'compound_drivers': [],
        'notes': ('Widespread Crisis (Phase 3) across the north; Emergency (Phase 4) in inaccessible, '
                  'worst-conflict-affected NE LGAs. (FAO-WFP separately flags Borno Catastrophe risk; '
                  'the FAOB itself does not tag Nigeria risk_of_famine.)'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/west-africa/nigeria',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'yemen': {
        'name': 'Yemen', 'region': 'east_africa',
        'current_pin': '14.0-14.99M', 'current_pin_numeric': 14_500_000,
        'projected_pin': '13.0-13.99M', 'projected_pin_numeric': 13_500_000,
        'pct_population': '35-40%',
        'highest_ipc_phase': 4, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Lower',
        'key_shocks': ['conflict', 'economy', 'weather'], 'compound_drivers': [],
        'notes': ('Emergency (Phase 4) in the west (SBA areas); Crisis (Phase 3) in IRG areas from '
                  'currency shortages and price transmission. Near-total food importer exposed to Hormuz/Red Sea.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/east-africa/yemen',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'south_sudan': {
        'name': 'South Sudan', 'region': 'east_africa',
        'current_pin': '8.0-8.99M', 'current_pin_numeric': 8_500_000,
        'projected_pin': '7.0-7.99M', 'projected_pin_numeric': 7_500_000,
        'pct_population': '50-55%',
        'highest_ipc_phase': 4, 'risk_of_famine': True, 'assistance_dependent': False,
        'famine_risk_areas': ('Risk of Famine in Akobo and Nyirol (Jonglei), Ulang and Nasir (Upper Nile) '
                              'if conflict isolates populations; Catastrophe (Phase 5) possible in east/north/center'),
        'trend_vs_last_year': 'Higher', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['conflict', 'economy', 'returnee_influx', 'weather'], 'compound_drivers': [],
        'notes': ('Highest PIN share of any FEWS NET country (50-55%). Conflict + flooding + below-average '
                  'rainfall drive Emergency (Phase 4); Jonglei and Upper Nile are highest concern.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/east-africa/south-sudan',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'afghanistan': {
        'name': 'Afghanistan', 'region': 'asia',
        'current_pin': '6.0-6.99M', 'current_pin_numeric': 6_500_000,
        'projected_pin': '7.0-7.99M', 'projected_pin_numeric': 7_500_000,
        'pct_population': '15-20%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Lower', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['economy', 'returnee_influx', 'weather'], 'compound_drivers': [],
        'notes': ('Crisis (Phase 3) in the NE and central highlands as the Dec lean season begins; high '
                  'returnee arrivals from Iran and Pakistan strain labor markets and support systems.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/asia/afghanistan',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'syria': {
        'name': 'Syria', 'region': 'middle_east',
        'current_pin': '5.0-5.99M', 'current_pin_numeric': 5_500_000,
        'projected_pin': '5.0-5.99M', 'projected_pin_numeric': 5_500_000,
        'pct_population': '20-25%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar*', 'trend_vs_5yr': 'Similar*',
        'key_shocks': ['conflict', 'economy'], 'compound_drivers': ['middle_east_fertilizer'],
        'aid_disruption': ('WFP HALVED emergency food aid May 2026 (1.3M -> 650,000 recipients; 14 '
                           'governorates -> 7) and HALTED the nationwide bread subsidy that fed up to 4M/day '
                           'via 300+ bakeries -- driven by funding cuts, not reduced need. WFP needs $189M '
                           '(Jun-Nov). Refugee aid also cut in Jordan/Egypt/Lebanon. (WFP, May 13 2026.)'),
        'notes': ('FAOB PIN is 5.0-5.99M (distinct from WFP\'s 7.2M "acutely food insecure" / 1.6M severe). '
                  'Widespread Crisis (Phase 3) persists; rising input costs, inflation, currency depreciation, '
                  'and elevated fuel prices push food costs ahead of the January lean season.'),
        'source': 'FEWS NET FAOB June 2026; WFP (May 2026)',
        'source_url': 'https://fews.net/middle-east-and-asia/syria',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'somalia': {
        'name': 'Somalia', 'region': 'east_africa',
        'current_pin': '6.0-6.99M', 'current_pin_numeric': 6_500_000,
        'projected_pin': '5.0-5.99M', 'projected_pin_numeric': 5_500_000,
        'pct_population': '25-30%',
        'highest_ipc_phase': 4, 'risk_of_famine': True, 'assistance_dependent': False,
        'famine_risk_areas': ('Bay, Bakool, and Gedo (crop-dependent agropastoral) face risk of Famine '
                              'through at least September if the gu rains end early or the xagaa rains fail'),
        'trend_vs_last_year': 'Higher', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['weather', 'conflict', 'economy'], 'compound_drivers': ['el_nino'],
        'notes': ('Multiple poor production seasons + worsening insecurity + fuel/shipping price transmission. '
                  'Emergency (Phase 4) across drought-affected south, central, north, and IDP settlements.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/east-africa/somalia',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'haiti': {
        'name': 'Haiti', 'region': 'lac',
        'current_pin': '3.0-3.49M', 'current_pin_numeric': 3_250_000,
        'projected_pin': '3.0-3.49M', 'projected_pin_numeric': 3_250_000,
        'pct_population': '25-30%',
        'highest_ipc_phase': 4, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['conflict', 'economy'], 'compound_drivers': [],
        'notes': ('Emergency (Phase 4) in Cite Soleil and Croix-des-Bouquets; displaced populations in '
                  'Port-au-Prince of highest concern. Armed-group control of routes + elevated transport/fuel costs.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/latin-america-and-caribbean/haiti',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'mozambique': {
        'name': 'Mozambique', 'region': 'southern_africa',
        'current_pin': '2.0-2.49M', 'current_pin_numeric': 2_250_000,
        'projected_pin': '2.5-2.99M', 'projected_pin_numeric': 2_750_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Lower', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['weather', 'conflict', 'economy'], 'compound_drivers': ['el_nino'],
        'notes': ('Crisis (Phase 3) in central/south (weather-driven) and north (conflict). Below-average '
                  'El Nino rainfall + high input and fuel costs depress labor opportunities.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/southern-africa/mozambique',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'kenya': {
        'name': 'Kenya', 'region': 'east_africa',
        'current_pin': '2.5-2.99M', 'current_pin_numeric': 2_750_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': 'less than 5%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': True,
        'trend_vs_last_year': 'Lower', 'trend_vs_5yr': 'Lower',
        'key_shocks': ['weather'], 'compound_drivers': [],
        'notes': ('Needs declining on favorable rains. Crisis (Phase 3) in pastoral areas; Crisis! (Phase 3!) '
                  'in Dadaab and Kakuma refugee camps, some households in Emergency (Phase 4).'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/east-africa/kenya',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'zimbabwe': {
        'name': 'Zimbabwe', 'region': 'southern_africa',
        'current_pin': '1.0-1.49M', 'current_pin_numeric': 1_250_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': '10-15%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Lower',
        'key_shocks': ['weather', 'economy'], 'compound_drivers': ['el_nino'],
        'notes': ('Crisis (Phase 3) in deficit-producing areas with poor 2026 harvests. Late, below-average '
                  'El Nino 2026/27 rains expected to constrain 2027 agricultural-labor income.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/southern-africa/zimbabwe',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'guatemala': {
        'name': 'Guatemala', 'region': 'lac',
        'current_pin': '2.0-2.49M', 'current_pin_numeric': 2_250_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['weather'], 'compound_drivers': ['el_nino'],
        'notes': ('Crisis (Phase 3) in the Dry Corridor, Alta Verapaz, Western Altiplano from El Nino '
                  'production risk + rising input costs.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/latin-america-and-caribbean/guatemala',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'chad': {
        'name': 'Chad', 'region': 'west_africa',
        'current_pin': '2.0-2.49M', 'current_pin_numeric': 2_250_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': True,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['refugee_influx', 'conflict', 'weather'], 'compound_drivers': [],
        'notes': ('Crisis! (Phase 3!) in refugee-hosting Ouaddai, Sila, Wadi Fira, Ennedi-Est from the '
                  'sustained Sudanese refugee + Chadian returnee influx; Lac Province Crisis from conflict.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/west-africa/chad',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'niger': {
        'name': 'Niger', 'region': 'west_africa',
        'current_pin': '2.0-2.49M', 'current_pin_numeric': 2_250_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['conflict', 'weather'], 'compound_drivers': ['middle_east_fertilizer'],
        'notes': ('Crisis (Phase 3) in Tillabery, Tahoua, Diffa. Below-average production expected from poor '
                  'rains AND high fertilizer costs the FAOB attributes to the Middle East escalation; '
                  'worst-affected pockets in Emergency (Phase 4).'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/west-africa/niger',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'cameroon': {
        'name': 'Cameroon', 'region': 'west_africa',
        'current_pin': '1.5-1.99M', 'current_pin_numeric': 1_750_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['conflict'], 'compound_drivers': [],
        'notes': ('Crisis (Phase 3) in conflict areas (NW, SW, Far North). Rising fuel, transport, and food '
                  'prices linked to global market pressures erode purchasing capacity.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/west-africa/cameroon',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'madagascar': {
        'name': 'Madagascar', 'region': 'southern_africa',
        'current_pin': '1.0-1.49M', 'current_pin_numeric': 1_250_000,
        'projected_pin': '1.5-1.99M', 'projected_pin_numeric': 1_750_000,
        'pct_population': 'less than 5%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['weather'], 'compound_drivers': [],
        'notes': ('Crisis (Phase 3) across the Grand South from early food-stock depletion; rainfall deficits '
                  'through September reduce cassava/sweet-potato harvests into the December lean season.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/southern-africa/madagascar',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'malawi': {
        'name': 'Malawi', 'region': 'southern_africa',
        'current_pin': '1.0-1.49M', 'current_pin_numeric': 1_250_000,
        'projected_pin': '1.0-1.49M', 'projected_pin_numeric': 1_250_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Lower', 'trend_vs_5yr': 'Lower',
        'key_shocks': ['weather', 'economy'], 'compound_drivers': ['el_nino'],
        'notes': ('Crisis (Phase 3) in southern Malawi as 2026-harvest stocks deplete; below-average El Nino '
                  'rains + high input/fuel costs limit labor opportunities.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/southern-africa/malawi',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'lebanon': {
        'name': 'Lebanon', 'region': 'middle_east',
        'current_pin': '1.0-1.49M', 'current_pin_numeric': 1_250_000,
        'projected_pin': '1.0-1.49M', 'projected_pin_numeric': 1_250_000,
        'pct_population': '25-30%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Higher*', 'trend_vs_5yr': 'Similar*',
        'key_shocks': ['conflict', 'economy'], 'compound_drivers': [],
        'notes': ('Crisis (Phase 3) in southern Lebanon (conflict, displacement, infrastructure damage) and '
                  'expanding countrywide. Refugees + displaced + poor Lebanese face rising difficulty. '
                  'Cross-references the wheat-Lebanon convergence; WFP cut Syrian-refugee cash aid (May 2026).'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/middle-east-and-asia/lebanon',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'venezuela': {
        'name': 'Venezuela', 'region': 'lac',
        'current_pin': '1.5-1.99M', 'current_pin_numeric': 1_750_000,
        'projected_pin': '1.0-1.49M', 'projected_pin_numeric': 1_250_000,
        'pct_population': 'less than 5%',
        'highest_ipc_phase': 2, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Lower*', 'trend_vs_5yr': 'Lower*',
        'key_shocks': ['economy'], 'compound_drivers': [],
        'notes': ('Stressed (Phase 2) with pockets of Crisis (Phase 3). December seasonal income (double '
                  'salaries, remittances) helps, but high inflation limits purchasing power.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/latin-america-and-caribbean/venezuela',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'burkina_faso': {
        'name': 'Burkina Faso', 'region': 'west_africa',
        'current_pin': '1.0-1.49M', 'current_pin_numeric': 1_250_000,
        'projected_pin': '750,000-999,999', 'projected_pin_numeric': 875_000,
        'pct_population': 'less than 5%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Lower',
        'key_shocks': ['conflict', 'weather'], 'compound_drivers': ['middle_east_fertilizer'],
        'notes': ('Crisis (Phase 3) in Karo-Peli and Djelgodji, where supply and aid delivery depend on '
                  'military-escorted convoys. Below-average yields from poor rains + Middle East crisis impact '
                  'on fertilizer prices and access.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/west-africa/burkina-faso',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'car': {
        'name': 'Central African Republic', 'region': 'west_africa',
        'current_pin': '750,000-999,999', 'current_pin_numeric': 875_000,
        'projected_pin': '750,000-999,999', 'projected_pin_numeric': 875_000,
        'pct_population': '10-15%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar*', 'trend_vs_5yr': 'Similar*',
        'key_shocks': ['conflict'], 'compound_drivers': [],
        'notes': ('Crisis (Phase 3) across conflict-affected areas; displacement and disrupted livelihoods '
                  'limit seasonal harvest improvements in the NE, SE, and NW.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/west-africa/central-african-republic',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'honduras': {
        'name': 'Honduras', 'region': 'lac',
        'current_pin': '500,000-749,999', 'current_pin_numeric': 625_000,
        'projected_pin': '500,000-749,999', 'projected_pin_numeric': 625_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 3, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar*', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['weather'], 'compound_drivers': ['el_nino'],
        'notes': ('Crisis (Phase 3) in the Dry Corridor; rest of country Stressed (Phase 2). El Nino rainfall '
                  'deficits + high input costs reduce smallholder primera/postrera harvests.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/latin-america-and-caribbean/honduras',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'burundi': {
        'name': 'Burundi', 'region': 'east_africa',
        'current_pin': '750,000-999,999', 'current_pin_numeric': 875_000,
        'projected_pin': '500,000-749,999', 'projected_pin_numeric': 625_000,
        'pct_population': '5-10%',
        'highest_ipc_phase': 2, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['economy', 'weather', 'refugee_influx', 'returnee_influx'], 'compound_drivers': [],
        'notes': ('Stressed (Phase 2) in the Imbo Plains and lowlands through December; exhausted Season B '
                  'stocks, fuel shortages, high prices, and refugee/returnee influx from DRC.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/east-africa/burundi',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'mali': {
        'name': 'Mali', 'region': 'west_africa',
        'current_pin': '1.0-1.49M', 'current_pin_numeric': 1_250_000,
        'projected_pin': '500,000-749,999', 'projected_pin_numeric': 625_000,
        'pct_population': 'less than 5%',
        'highest_ipc_phase': 4, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar', 'trend_vs_5yr': 'Higher',
        'key_shocks': ['conflict', 'economy', 'weather'], 'compound_drivers': [],
        'notes': ('Emergency (Phase 4) now expected in Kidal through December from severe market/trade '
                  'disruption; Crisis (Phase 3) persists in Menaka. Fuel-crisis and transport costs limit access.'),
        'source': 'FEWS NET FAOB June 2026', 'source_url': 'https://fews.net/west-africa/mali',
        'source_as_of': '2026-06', 'data_pending': False,
    },

    'el_salvador': {
        'name': 'El Salvador', 'region': 'lac',
        'current_pin': '100,000-249,999', 'current_pin_numeric': 175_000,
        'projected_pin': '100,000-249,999', 'projected_pin_numeric': 175_000,
        'pct_population': 'less than 5%',
        'highest_ipc_phase': 2, 'risk_of_famine': False, 'assistance_dependent': False,
        'trend_vs_last_year': 'Similar*', 'trend_vs_5yr': 'Similar',
        'key_shocks': ['weather'], 'compound_drivers': ['el_nino'],
        'notes': ('Stressed (Phase 2) with a growing share in Crisis (Phase 3) across the Dry Corridors; '
                  'high temperatures and erratic/El Nino rainfall delay planting and erode stocks.'),
        'source': 'FEWS NET FAOB June 2026',
        'source_url': 'https://fews.net/latin-america-and-caribbean/el-salvador',
        'source_as_of': '2026-06', 'data_pending': False,
    },
}

# ============================================================
# PRESENCE COUNTRIES -- canonical FEWS NET coverage set (June 2026)
# The 26 above carry full FAOB records; the rest are presence countries WITHOUT
# a detailed PIN row in the June FAOB (lower needs / remotely monitored). Listed
# for convergence dedupe + Africa coverage; intentionally NOT given numbers.
# ============================================================
PRESENCE_COUNTRIES = {
    'east_africa':     ['burundi', 'djibouti', 'ethiopia', 'kenya', 'rwanda', 'somalia',
                        'south_sudan', 'sudan', 'tanzania', 'uganda', 'yemen'],
    'southern_africa': ['angola', 'drc', 'lesotho', 'madagascar', 'malawi', 'mozambique',
                        'zambia', 'zimbabwe'],
    'west_africa':     ['benin', 'burkina_faso', 'cameroon', 'car', 'chad', 'cote_divoire',
                        'guinea', 'liberia', 'mali', 'mauritania', 'niger', 'nigeria',
                        'senegal', 'sierra_leone', 'togo'],
    'asia':            ['afghanistan', 'pakistan', 'tajikistan'],
    'middle_east':     ['gaza', 'iran', 'iraq', 'lebanon', 'syria', 'ukraine', 'yemen'],
    'lac':             ['colombia', 'ecuador', 'el_salvador', 'guatemala', 'haiti',
                        'honduras', 'nicaragua', 'venezuela'],
}

# ============================================================
# ACCESSORS
# ============================================================
def meta():
    """Module-level provenance for footers / 'data as of' lines."""
    return dict(META)


def get_country(code):
    """Full record for a country code, or None if not in the FAOB detail set."""
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
    """Flat canonical FEWS NET coverage list (codes), deduped."""
    seen, flat = set(), []
    for region_list in PRESENCE_COUNTRIES.values():
        for c in region_list:
            if c not in seen:
                seen.add(c)
                flat.append(c)
    return flat


def get_panel(code):
    """Compact dict for a stability-page Food Security card. None if the country
    has no FAOB record (caller renders 'no FEWS data')."""
    rec = get_country(code)
    if not rec:
        return None
    return {
        'name':                rec['name'],
        'current_pin':         rec.get('current_pin'),
        'projected_pin':       rec.get('projected_pin'),
        'pct_population':      rec.get('pct_population'),
        'highest_ipc_phase':   rec.get('highest_ipc_phase'),
        'ipc_label':           IPC_PHASES.get(rec.get('highest_ipc_phase'), 'Unknown'),
        'risk_of_famine':      rec.get('risk_of_famine', False),
        'famine_risk_areas':   rec.get('famine_risk_areas'),
        'assistance_dependent':rec.get('assistance_dependent', False),
        'trend_vs_last_year':  rec.get('trend_vs_last_year'),
        'trend_vs_5yr':        rec.get('trend_vs_5yr'),
        'key_shocks':          rec.get('key_shocks', []),
        'compound_drivers':    rec.get('compound_drivers', []),
        'aid_disruption':      rec.get('aid_disruption'),
        'health_overlay':      rec.get('health_overlay'),
        'notes':               rec.get('notes'),
        'source':              rec.get('source'),
        'source_url':          rec.get('source_url'),
        'source_as_of':        rec.get('source_as_of'),
        'cycle':               META['cycle'],
        'projection_for':      META['projection_for'],
    }


def famine_risk_countries():
    """Codes the FAOB flags risk_of_famine -- drives the convergence escalator.
    (June 2026: sudan, south_sudan, somalia.)"""
    return [code for code, rec in FEWS_COUNTRIES.items() if rec.get('risk_of_famine')]


def high_severity_countries(min_phase=4):
    """Codes whose highest IPC area classification >= min_phase (Emergency by
    default) -- SEED the humanitarian convergence detector (news then amplifies)."""
    return [code for code, rec in FEWS_COUNTRIES.items()
            if (rec.get('highest_ipc_phase') or 0) >= min_phase]


def assistance_dependent_countries():
    """Codes carrying the FAOB '!' marker -- at least one phase worse WITHOUT aid.
    These are the places most exposed to the WFP/funding-cut pattern."""
    return [code for code, rec in FEWS_COUNTRIES.items() if rec.get('assistance_dependent')]


def countries_with_driver(driver):
    """Codes whose compound_drivers include `driver` (e.g. 'el_nino',
    'middle_east_fertilizer') -- cross-links to the GPI commodity convergences."""
    return [code for code, rec in FEWS_COUNTRIES.items()
            if driver in (rec.get('compound_drivers') or [])]


def pin_ranking(limit=None, by='projected'):
    """Countries sorted by PIN desc. by='projected' (FAOB headline order) or
    'current'. Records without a numeric value sort last."""
    key_field = 'projected_pin_numeric' if by == 'projected' else 'current_pin_numeric'
    ranked = sorted(
        all_countries(),
        key=lambda r: (r.get(key_field) is not None, r.get(key_field) or 0),
        reverse=True,
    )
    return ranked[:limit] if limit else ranked
