"""
Asifah Analytics -- Prediction Markets WATCHLIST  (v1.1.0, Nov 21 2026)

v1.1.0 (Nov 21 2026): 55 markets (was 37). us_iran_ceasefire re-pointed (the
"continues through" ladder ran out after the ceasefire broke); Iran blockade,
Kharg, airspace, Hormuz deal, US-Iran talks, Iran leadership; Turkey (Greece
clash, F-35, early election); Israel strikes on Lebanon (daily, rolls monthly);
Russia strikes an EU state; the Nov 13 FAA outage (cyber); NVIDIA after Huang.
Test applied to every add (Rachel, Nov 21): "the big things that could have a
real butterfly effect on geopolitics".

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
  ref_template    Polymarket events that open a new slug each month: '{month}'
                  and '{year}' are filled in (this month first, then next).
  fades_after     'YYYY-MM-DD': after this date the item shows faded as old news
                  (sorted last; a strip of only faded items collapses).
  retire_after    'YYYY-MM-DD': stop reading the item after this date (one-off
                  questions such as the FAA outage), so it drops off quietly.
  osint           'none' when no Asifah tracker reads the question (cyber):
                  the page then says so instead of comparing with a level.
  osint_note      the sentence shown in that case.

SELECTORS added in v1.1.0
  'today'    a daily ladder ("strike on Nov 22?"): shows the next open day only.

Rule (Rachel, Nov 5 2026): markets sit BESIDE the score. They never raise or
lower an Asifah level. Their one job in the scoring layer is the divergence flag.
"""

WATCHLIST = [
    # ── Middle East ────────────────────────────────────────────────────
    {'id': 'us_iran_ceasefire', 'label': 'Does a two-week pause in US strikes on Iran take hold?',
     'source': 'polymarket', 'ref': 'us-x-iran-effective-ceasefire-begins-by-2-week-pause-20261108',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'kinetic',
     'pages': ['gpi', 'military', 'region:me', 'iran'], 'countries': ['iran', 'us'],
     'note': 'Settles YES only after 14 straight days with no US air or missile strike hitting Iran '
             '(re-pointed Nov 21: the "ceasefire continues" contract ran out when the ceasefire broke).'},
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

    {'id': 'iran_blockade_end', 'label': 'US announces an end to the naval blockade of Iran?',
     'source': 'polymarket', 'ref': 'us-announces-end-of-iranian-blockade-byptptpt-20260713152715080',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'economic',
     'pages': ['gpi', 'commodities', 'market-watch', 'region:me', 'iran'], 'countries': ['iran'],
     'note': 'Needs an official US announcement of a general end or suspension; partial exemptions do not count.'},
    {'id': 'kharg_island', 'label': 'Kharg Island (Iran\'s main oil terminal) leaves Iranian control?',
     'source': 'polymarket', 'ref': 'kharg-island-no-longer-under-iranian-control-by-march-31',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'commodities', 'region:me', 'iran'], 'countries': ['iran']},
    {'id': 'iran_airspace', 'label': 'Iran closes its airspace completely?',
     'source': 'polymarket', 'ref': 'iran-full-airspace-closure-byptptpt-20260625195253028',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:me', 'iran'], 'countries': ['iran']},
    {'id': 'us_iran_hormuz_deal', 'label': 'US-Iran agreement on the Strait of Hormuz?',
     'source': 'polymarket', 'ref': 'us-iran-hormuz-agreement-byptptpt-20260803235957575',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['gpi', 'commodities', 'region:me', 'iran'], 'countries': ['iran']},
    {'id': 'us_iran_meeting', 'label': 'Next senior US-Iran diplomatic meeting?',
     'source': 'polymarket', 'ref': 'next-us-iran-senior-diplomatic-meeting-byptptpt',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['region:me', 'iran'], 'countries': ['iran']},
    {'id': 'iran_leadership_change', 'label': 'Change at the top of Iran\'s leadership?',
     'source': 'polymarket', 'ref': 'iran-leadership-change-by',
     'selector': 'ladder', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:me', 'iran'], 'countries': ['iran']},
    {'id': 'israel_strikes_lebanon_today', 'label': 'Israeli air or missile strike on Lebanon (next day)?',
     'source': 'polymarket', 'ref': 'israel-military-action-against-lebanon-on-november-2026',
     'ref_template': 'israel-military-action-against-lebanon-on-{month}-{year}',
     'selector': 'today', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:me', 'lebanon', 'israel'], 'countries': ['lebanon', 'israel'],
     'note': 'One contract per day (Jerusalem time). Counts air or missile strikes that hit Lebanon; '
             'artillery, drones intercepted and ground fire do not count.'},
    {'id': 'greece_turkey_clash', 'label': 'Greece-Turkey military engagement?',
     'source': 'polymarket', 'ref': 'greece-x-turkey-military-engagement-by-june-30',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['military', 'region:europe', 'turkey', 'greece'], 'countries': ['turkey', 'greece']},
    {'id': 'turkey_f35', 'label': 'Turkey rejoins the F-35 programme?',
     'source': 'polymarket', 'ref': 'turkey-rejoins-f-35-program-byptptpt-20260708215709215',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'diplomatic',
     'pages': ['region:europe', 'turkey'], 'countries': ['turkey']},
    {'id': 'turkey_early_election', 'label': 'Turkey calls an early presidential election in 2026?',
     'source': 'polymarket', 'ref': 'will-turkey-schedule-early-presidential-elections-in-2026',
     'selector': 'single', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['region:europe', 'turkey'], 'countries': ['turkey']},

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
    {'id': 'russia_strikes_eu', 'label': 'Russian air or missile strike on an EU member state?',
     'source': 'polymarket', 'ref': 'russia-military-action-against-eu-country-byptptpt',
     'selector': 'ladder', 'yes_means': 'more_pressure', 'axis': 'kinetic',
     'pages': ['gpi', 'military', 'region:europe', 'russia'], 'countries': ['russia'],
     'note': 'Strikes that hit EU territory only; intercepted munitions, drones shot down and cyber do not count.'},
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

    # ── Cyber & infrastructure (Nov 21 2026) ───────────────────────────
    # No Asifah tracker reads cyber yet, so these carry osint='none': the page
    # says "no tracker" instead of comparing with a country level.
    {'id': 'faa_hack', 'label': 'US officially attributes the Nov 13 FAA outage to a hack?',
     'source': 'polymarket', 'ref': 'faa-outage-attributed-to-hack',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'governance',
     'pages': ['market-watch', 'cyber'], 'countries': [], 'fades_after': '2026-11-30', 'retire_after': '2026-12-08',
     'osint': 'none',
     'osint_note': 'Asifah has no cyber tracker yet, so there is nothing of ours to set beside this. Unread, not calm.',
     'note': 'Needs an official US government attribution (or charges) by Nov 30. "Suspected" or "consistent with" does not count.'},
    {'id': 'faa_foreign', 'label': 'US officially attributes the FAA outage to a foreign actor?',
     'source': 'polymarket', 'ref': 'faa-outage-attributed-to-a-foreign-actor',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'governance',
     'pages': ['market-watch', 'cyber'], 'countries': [], 'fades_after': '2026-11-30', 'retire_after': '2026-12-08',
     'osint': 'none',
     'osint_note': 'Asifah has no cyber tracker yet, so there is nothing of ours to set beside this. Unread, not calm.',
     'note': 'Any foreign state, its forces or intelligence services, or a group based abroad. Official attribution by Nov 30 only.'},
    {'id': 'faa_iran', 'label': 'US officially attributes the FAA outage to Iran?',
     'source': 'polymarket', 'ref': 'faa-outage-attributed-to-iran',
     'selector': 'single', 'yes_means': 'more_pressure', 'axis': 'governance',
     'pages': ['market-watch', 'cyber'], 'countries': [], 'fades_after': '2026-11-30', 'retire_after': '2026-12-08',
     'osint': 'none',
     'osint_note': 'Asifah reads Iran on the war, not on cyber: no tracker of ours measures this. Unread, not calm.',
     'note': 'Must name the Iranian state, IRGC or intelligence services. Blaming a proxy (e.g. Hizballah) alone does not count.'},
    {'id': 'faa_cause', 'label': 'What do officials say caused the FAA ground stop?',
     'source': 'polymarket', 'ref': 'what-technical-failure-caused-the-faas-nationwide-ground-stop',
     'selector': 'field', 'yes_means': 'neutral', 'axis': 'governance',
     'pages': ['market-watch', 'cyber'], 'countries': [], 'fades_after': '2026-11-30', 'retire_after': '2026-12-08',
     'osint': 'none',
     'note': 'Not a single race: several causes can settle YES. Shows the likeliest.'},

    # ── NVIDIA after Huang (Nov 21 2026) ───────────────────────────────
    {'id': 'nvidia_huang_return', 'label': 'Jensen Huang returns to a formal role at NVIDIA?',
     'source': 'polymarket', 'ref': 'jensen-huang-rejoins-nvidia-byptptpt',
     'selector': 'ladder', 'yes_means': 'less_pressure', 'axis': 'economic',
     'pages': ['market-watch'], 'countries': [],
     'note': 'NVIDIA announced his resignation as CEO and director on Nov 12 2026. Honorary or informal roles do not count.'},
    {'id': 'nvidia_next_ceo', 'label': 'Who is named NVIDIA\'s next CEO?',
     'source': 'polymarket', 'ref': 'next-ceo-of-nvidia',
     'selector': 'field', 'yes_means': 'neutral', 'axis': 'economic',
     'pages': ['market-watch'], 'countries': [],
     'note': 'Interim CEOs do not count. "Jensen Huang (No Change)" means no successor is named by end-2028.'},
    {'id': 'largest_company', 'label': 'World\'s largest company at the end of December?',
     'source': 'polymarket', 'ref': 'largest-company-end-of-december-2026',
     'selector': 'field', 'yes_means': 'neutral', 'axis': 'economic',
     'pages': ['market-watch'], 'countries': []},
]
