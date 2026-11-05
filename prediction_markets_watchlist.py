"""
Asifah Analytics -- Prediction Markets WATCHLIST  (v1.0.1, Nov 5 2026)

This is the ONLY file to edit when adding, removing or re-pointing a market.
The engine (prediction_markets.py) never needs to change for that.

HOW TO READ AN ENTRY
  id         short unique name (letters, numbers, underscores). Used in URLs and history.
  label      the plain-English question shown on the page.
  source     'polymarket' or 'kalshi'.
  ref        Polymarket: the event SLUG (the end of polymarket.com/event/<slug>).
             Kalshi: the SERIES ticker (e.g. KXHORMUZWEEKLY).
  selector   how to choose the market(s) inside the event:
               'single'    -- one yes/no market.
               'ladder'    -- a set of deadlines ("...by Dec 31?", "...by Mar 31?").
                              Shows the nearest open deadline, and any deadline that
                              SETTLED in the last few days (often the real news).
               'field'     -- a race between candidates or outcomes. Shows the leader.
               'threshold' -- a price/number ladder ("above 20", "$115 or above").
                              Shows the strike traders are most active on, and the
                              biggest move across all strikes.
  yes_means  what a YES does to pressure in Asifah's terms:
               'more_pressure' (war, closure, collapse), 'less_pressure'
               (ceasefire, deal, reopening), or 'neutral' (elections, rates).
  axis       kinetic / economic / diplomatic / humanitarian / governance.
  pages      where it shows: 'gpi', 'military', 'commodities', 'market-watch',
             'region:me', 'region:europe', 'region:asia', 'region:africa',
             'region:wha', and country slugs ('iran', 'lebanon', 'uk', ...).
  countries  Asifah country ids used for the divergence check (our level vs the odds).

OPTIONAL
  event_min_days  Kalshi only: skip events closing sooner than this many days
                  (so "recession this year?" rolls to next year on its own).
  pick            a few words; only markets whose wording contains them are used.
  note            a caveat shown with the item (contract wording traps etc.).
  status_quo      True for "continues through <date>" ladders: there a YES only
                  means nothing happened, so only an early NO counts as news.
  unit            threshold items: what the number counts ("transit calls").

Rule (Rachel, Nov 5 2026): markets sit BESIDE the score. They never raise or
lower an Asifah level. Their one job in the scoring layer is the divergence flag.
"""

WATCHLIST = [
    # ── Middle East ────────────────────────────────────────────────────
    {'id': 'us_iran_ceasefire', 'label': 'Does the US-Iran ceasefire hold?',
     'source': 'polymarket', 'ref': 'us-iran-ceasefire-continues-throughptptpt',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'kinetic',
     'pages': ['gpi', 'military', 'region:me', 'iran'], 'countries': ['iran', 'us'],
     'status_quo': True,
     'note': 'Settles NO on any US air or missile strike that hits Iran, even a limited one.'},
    {'id': 'israel_iran_ceasefire', 'label': 'Does the Israel-Iran ceasefire hold?',
     'source': 'polymarket', 'ref': 'israel-x-iran-ceasefire-continues-throughptptpt-20260716224448963',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'kinetic',
     'pages': ['gpi', 'military', 'region:me', 'iran', 'israel'], 'countries': ['iran', 'israel'],
     'status_quo': True},
    {'id': 'us_invade_iran', 'label': 'US ground offensive into Iran before 2027?',
     'source': 'polymarket', 'ref': 'will-the-us-invade-iran-before-2027',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:me', 'iran'], 'countries': ['iran']},
    {'id': 'iran_regime_fall', 'label': 'Iranian regime falls before 2027?',
     'source': 'polymarket', 'ref': 'will-the-iranian-regime-fall-by-the-end-of-2026',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'governance',
     'pages': ['region:me', 'iran'], 'countries': ['iran']},
    {'id': 'us_iran_deal', 'label': 'US-Iran final nuclear deal?',
     'source': 'polymarket', 'ref': 'us-iran-final-nuclear-deal-by-20260621201254412',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['gpi', 'region:me', 'iran'], 'countries': ['iran']},
    {'id': 'hormuz_normal', 'label': 'When does Strait of Hormuz traffic return to normal?',
     'source': 'kalshi', 'ref': 'KXHORMUZNORM',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'economic',
     'pages': ['gpi', 'commodities', 'military', 'market-watch', 'region:me', 'iran'],
     'countries': ['iran', 'oman', 'uae']},
    {'id': 'hormuz_weekly', 'label': 'Ships through Hormuz this week (traders\' estimate)',
     'source': 'kalshi', 'ref': 'KXHORMUZWEEKLY',
     'selector': 'threshold', 'yes_means': 'less_pressure', 'axis': 'economic', 'unit': 'transit calls',
     'pages': ['commodities', 'military', 'region:me'], 'countries': ['iran', 'oman', 'uae'],
     'note': 'Counts transit calls reported by IMF PortWatch for the week.'},
    {'id': 'bab_el_mandeb', 'label': 'Bab el-Mandeb effectively closed?',
     'source': 'polymarket', 'ref': 'bab-el-mandeb-strait-effectively-closed-by',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['gpi', 'commodities', 'military', 'region:me', 'yemen'], 'countries': ['yemen']},
    {'id': 'saudi_houthi_ceasefire', 'label': 'Saudi-Houthi ceasefire announced?',
     'source': 'polymarket', 'ref': 'saudi-houthi-ceasefire-agreement-announced-by',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['region:me', 'yemen', 'saudi_arabia'], 'countries': ['yemen', 'saudi_arabia']},
    {'id': 'israel_leaves_lebanon', 'label': 'Israel withdraws from Lebanon?',
     'source': 'polymarket', 'ref': 'israel-withdraws-from-lebanon-by',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'kinetic',
     'pages': ['region:me', 'lebanon', 'israel'], 'countries': ['lebanon', 'israel']},
    {'id': 'hizballah_disarm', 'label': 'Hizballah disarms?',
     'source': 'polymarket', 'ref': 'will-hezbollah-disarm-by-march-31',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['region:me', 'lebanon'], 'countries': ['lebanon']},
    {'id': 'israel_government', 'label': 'When is Israel\'s next government formed?',
     'source': 'polymarket', 'ref': 'next-israeli-government-formed-by',
     'selector': 'ladder', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:me', 'israel'], 'countries': ['israel']},
    {'id': 'netanyahu_out', 'label': 'Netanyahu out of office?',
     'source': 'polymarket', 'ref': 'netanyahu-out-before-2027',
     'selector': 'ladder', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:me', 'israel'], 'countries': ['israel']},
    {'id': 'israel_turkey_clash', 'label': 'Israel-Turkey military clash before 2027?',
     'source': 'polymarket', 'ref': 'israel-x-turkey-military-clash-before-2027',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:me', 'region:europe', 'turkey', 'israel'],
     'countries': ['israel', 'turkey']},

    # ── Europe ─────────────────────────────────────────────────────────
    {'id': 'russia_ukraine_ceasefire', 'label': 'Russia-Ukraine ceasefire agreement?',
     'source': 'polymarket', 'ref': 'russia-x-ukraine-ceasefire-agreement-by',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['gpi', 'military', 'region:europe', 'ukraine', 'russia'],
     'countries': ['ukraine', 'russia']},
    {'id': 'nato_russia_clash', 'label': 'NATO-Russia military clash?',
     'source': 'polymarket', 'ref': 'nato-x-russia-military-clash-in-2025',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['gpi', 'military', 'region:europe', 'russia', 'uk'], 'countries': ['russia']},
    {'id': 'putin_out', 'label': 'Putin out as president?',
     'source': 'polymarket', 'ref': 'putin-out-before-2027',
     'selector': 'ladder', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:europe', 'russia'], 'countries': ['russia']},
    {'id': 'uk_recession', 'label': 'UK recession in 2026?',
     'source': 'polymarket', 'ref': 'uk-recession-in-2026',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['region:europe', 'uk', 'market-watch'], 'countries': ['uk']},

    # ── Asia ───────────────────────────────────────────────────────────
    {'id': 'china_taiwan_clash', 'label': 'China-Taiwan military clash before 2027?',
     'source': 'polymarket', 'ref': 'china-x-taiwan-military-clash-before-2027',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['gpi', 'military', 'region:asia', 'china', 'taiwan'], 'countries': ['china', 'taiwan']},
    {'id': 'china_invades_taiwan', 'label': 'China invades Taiwan by end of 2027?',
     'source': 'polymarket', 'ref': 'will-china-invade-taiwan-by-december-31-2027',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:asia', 'china', 'taiwan'], 'countries': ['china', 'taiwan']},
    {'id': 'china_philippines_clash', 'label': 'China-Philippines military clash before 2027?',
     'source': 'polymarket', 'ref': 'china-x-philippines-military-clash-before-2027-20260723214807932',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:asia', 'philippines', 'china'], 'countries': ['china', 'philippines']},
    {'id': 'dprk_invades', 'label': 'North Korea invades South Korea before 2027?',
     'source': 'polymarket', 'ref': 'will-north-korea-invade-south-korea-before-2027',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:asia', 'north_korea', 'south_korea'], 'countries': ['dprk', 'south_korea']},
    {'id': 'india_strikes_pakistan', 'label': 'India strikes Pakistan?',
     'source': 'polymarket', 'ref': 'india-strike-on-pakistan-by',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:asia', 'india', 'pakistan'], 'countries': ['india', 'pakistan']},

    # ── Western Hemisphere ─────────────────────────────────────────────
    {'id': 'venezuela_leader', 'label': 'Who leads Venezuela at the end of 2026?',
     'source': 'polymarket', 'ref': 'venezuela-leader-end-of-2026',
     'selector': 'field', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:wha', 'venezuela'], 'countries': ['venezuela']},
    {'id': 'us_strike_cuba', 'label': 'US military action against Cuba?',
     'source': 'polymarket', 'ref': 'us-strike-on-cuba-by',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:wha', 'cuba'], 'countries': ['cuba', 'us']},
    {'id': 'diaz_canel_out', 'label': 'Diaz-Canel out as Cuba\'s leader?',
     'source': 'polymarket', 'ref': 'miguel-daz-canel-out-as-leader-of-cuba-by-june-30',
     'selector': 'ladder', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:wha', 'cuba'], 'countries': ['cuba']},
    {'id': 'us_strike_colombia', 'label': 'US strike on Colombia?',
     'source': 'polymarket', 'ref': 'us-strike-on-colombia-by-january-31',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:wha', 'colombia'], 'countries': ['colombia', 'us']},
    {'id': 'argentina_2027', 'label': 'Argentina 2027 presidential election: who leads?',
     'source': 'polymarket', 'ref': 'argentina-presidential-election-winner',
     'selector': 'field', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:wha', 'argentina'], 'countries': ['argentina']},

    # ── Africa ─────────────────────────────────────────────────────────
    {'id': 'sudan_ceasefire', 'label': 'Sudan civil war ceasefire?',
     'source': 'polymarket', 'ref': 'sudan-civil-war-ceasefire-by',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'kinetic',
     'pages': ['region:africa', 'sudan'], 'countries': ['sudan']},
    {'id': 'ebola_spread', 'label': 'Which countries see an Ebola case in 2026?',
     'source': 'polymarket', 'ref': 'which-countries-will-have-an-ebola-case-in-2026',
     'selector': 'field', 'yes_means': 'more_pressure', 'axis': 'humanitarian',
     'pages': ['gpi', 'region:africa', 'drc', 'south_sudan'], 'countries': ['drc', 'kenya', 'south_sudan', 'uganda'],
     'note': 'Not a single race: each country is its own yes/no. Shows the likeliest.'},
    {'id': 'somali_piracy', 'label': 'Somali pirates seize a vessel?',
     'source': 'polymarket', 'ref': 'somali-pirates-successfully-seize-a-vessel-byptptpt',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['commodities', 'region:africa', 'somalia'], 'countries': ['somalia']},

    # ── Markets & commodities ──────────────────────────────────────────
    {'id': 'us_recession', 'label': 'US recession (official NBER call) next year?',
     'source': 'kalshi', 'ref': 'KXRECSSNBER', 'event_min_days': 120,
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['gpi', 'market-watch', 'us'], 'countries': ['us']},
    {'id': 'sp500_low', 'label': 'How low does the S&P 500 go this year?',
     'source': 'kalshi', 'ref': 'KXINXMINY',
     'selector': 'threshold', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['market-watch'], 'countries': ['us']},
    {'id': 'fed_next', 'label': 'Next Fed decision',
     'source': 'kalshi', 'ref': 'KXFEDDECISION',
     'selector': 'field', 'yes_means': 'neutral', 'axis': 'economic',
     'pages': ['market-watch'], 'countries': ['us']},
    {'id': 'fed_emergency', 'label': 'Fed emergency meeting this year?',
     'source': 'kalshi', 'ref': 'KXFEDMEET',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['market-watch'], 'countries': ['us']},
    {'id': 'wti_high', 'label': 'How high does WTI oil go by year-end?',
     'source': 'kalshi', 'ref': 'KXWTIMAX', 'event_min_days': 20,
     'selector': 'threshold', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['commodities', 'market-watch'], 'countries': []},
    {'id': 'crude_record', 'label': 'Crude oil hits an all-time high?',
     'source': 'polymarket', 'ref': 'crude-oil-all-time-high-by',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'economic',
     'pages': ['gpi', 'commodities', 'market-watch'], 'countries': []},
]
