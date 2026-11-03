"""
tracker_meanings.py -- Asifah Analytics -- ME backend
================================================================================
WHAT THE WORDS ON THE MILITARY, COMMODITIES AND MARKET WATCH PAGES MEAN.

THE QUESTION (Rachel, Nov 3 2026)
  "What does it MEAN when we discuss conflict repricing, what does it MEAN that
  the Strait of Hormuz is contested, what does it MEAN that there is a
  URANIUM-ROUTE-DEPENDENCY convergence? How does this play into local,
  regional and global geopolitics, global economies?"

WHAT THIS FILE IS
  A reference library, written once, that answers "what does this mean" for
  every term the three pages light up: chokepoints, chokepoint pairs, theatre
  and chokepoint levels, the market-repricing states, the fragility bands.
  Each entry says what the thing IS in plain words, then what it means at
  four altitudes: LOCAL (the country or waterway itself), REGIONAL, GLOBAL,
  and ECONOMY (prices, trade, money).

  Two readers use it:
    1. The PAGES, directly, through /api/tracker-voice. This needs no AI and
       is always on: if the plain-language writer has not run, or the credits
       are gone, every lit item still carries its meaning.
    2. The WRITER (tracker_voice.py), as the meaning_basis for each lit item.
       The writer turns "what this is" into "what it means TODAY", given what
       the sensors saw.

  Commodity convergences are NOT duplicated here. Their meaning already lives
  in convergence_registry.py ('detail' and 'facts', Rachel's own words); this
  file only knows how to pull it out (see registry_meaning()).

HONESTY
  Figures in here are approximate, carry their basis, and are flagged
  'verified': False where they are Claude research awaiting Rachel's
  correction pass (the same convention as commodity_web.py). They describe
  STRUCTURE (what flows where), never the current state. The current state is
  what the sensors report.

PURE MODULE. No Redis, no HTTP, no Flask.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import re

__version__ = '1.0.0'
AS_OF = '2026-11-03'
RESEARCH_BASIS = 'Claude research, Nov 3 2026 -- approximate figures, verify'


# ════════════════════════════════════════════════════════════════════════
# LEVEL WORDS -- what each level on each page measures
# ════════════════════════════════════════════════════════════════════════

CHOKEPOINT_LEVEL_MEANING = {
    'open': 'No reporting this scan suggests trouble in the passage.',
    'monitored': ('Above-normal reporting about the passage, but no attacks, seizures '
                  'or closures in it. Worth watching, not yet a problem for shipping.'),
    'contested': ('Reporting describes active confrontation: threats to ships, '
                  'boardings, warships shadowing each other, or insurers marking the '
                  'area as dangerous. Ships still pass, at higher cost and risk.'),
    'disrupted': ('Reporting describes ships being attacked, seized or turned away, a '
                  'declared blockade, or traffic rerouting. Normal passage is broken.'),
}

THEATRE_LEVEL_MEANING = {
    'normal': 'No region-wide military escalation in this scan.',
    'elevated': ('More military activity and reporting than usual in the region, below '
                 'the level of sustained high tempo.'),
    'high': ('Sustained, high-tempo military activity by several actors in the region at '
             'once.'),
    'surge': ('Region-wide surge: several actors at peak tempo at the same time. The '
              'level reads reporting about deployments, exercises and strikes, not a '
              'count of battles.'),
}

COMMODITY_LEVEL_MEANING = {
    'normal': 'Routine news flow about the commodity.',
    'monitor': 'Slightly more news than usual; nothing that moves supply yet.',
    'elevated': ('More, and more serious, reporting than usual: supply worries, policy '
                 'moves or price swings are in the news.'),
    'high': ('Heavy, serious reporting: supply disruptions, export restrictions or sharp '
             'price moves are being reported across several outlets.'),
    'surge': ('Peak news pressure. The level measures the weight of reporting, not the '
              'price itself; check the price line before reading it as a shortage.'),
}

FRAGILITY_BAND_MEANING = {
    'normal': ('Few of the conditions that came before past market collapses are present. '
               'The forest is not unusually dry.'),
    'elevated': ('Several conditions that came before past market collapses are present at '
                 'once. Not a warning of a crash; a market with less room to absorb a shock.'),
    'high': ('Many pre-collapse conditions at once. Historically this is where shocks '
             'travelled further than their size justified.'),
    'critical': ('Most pre-collapse conditions at once. The rarest band; in the past it has '
                 'appeared ahead of the largest drawdowns, and also in years when nothing '
                 'broke.'),
}


# ════════════════════════════════════════════════════════════════════════
# GENERAL TERMS
# ════════════════════════════════════════════════════════════════════════

TERMS = {
    'chokepoint': {
        'name': 'Maritime chokepoint',
        'plain': ('A narrow sea passage that a large share of world trade must use, '
                  'because the way around is much longer or does not exist.'),
        'local': 'The coastal states can tax, protect, threaten or close it.',
        'regional': 'Neighbours that export or import through it share its risk.',
        'global': ('Trouble in one chokepoint shows up worldwide as delays, longer routes '
                   'and higher freight and insurance costs.'),
        'economy': ('Ships rerouting burn more fuel and spend more days at sea; insurers '
                    'add war-risk premiums; those costs pass into the price of goods and '
                    'energy.'),
    },
    'coupled_chokepoints': {
        'name': 'Coupled chokepoints',
        'plain': ('Two passages that are each other\'s back-up, or that are pressed by the '
                  'same actor, both under pressure at the same time.'),
        'local': 'The usual detour is no longer a safe detour.',
        'regional': 'The pressure is coordinated, or at least compounding, across a region.',
        'global': ('When the back-up route is also contested, rerouting stops being a '
                   'cost and starts being a capacity problem.'),
        'economy': ('Freight and insurance costs rise faster than when one passage is in '
                    'trouble, because there is nowhere cheaper to go.'),
    },
    'neo': {
        'name': 'Evacuation / drawdown signals',
        'plain': ('Reporting that governments are moving their citizens or non-essential '
                  'embassy staff out of a country (a "NEO" is a non-combatant evacuation '
                  'operation).'),
        'local': ('Governments with the best information are acting to reduce their '
                  'exposure. It is one of the most expensive signals to send, so it is '
                  'rarely sent lightly.'),
        'regional': 'Neighbouring posts often review their own posture at the same time.',
        'global': ('Evacuations are read by markets and other governments as a judgement '
                   'about the next weeks, not the last ones.'),
        'economy': 'Airlines suspend routes and insurers reprice travel and cargo cover.',
    },
    'conflict_repricing': {
        'name': 'Conflict repricing',
        'plain': ('Whether investors\' money agrees with the diplomats. Asifah watches four '
                  'market gauges for a war zone -- the country\'s shares, its currency, its '
                  'defence companies against the wider market, and oil -- and asks whether '
                  'they move together the way they do when traders believe peace (or war) is '
                  'real.'),
        'local': ('If the gauges price peace, the country borrows more cheaply and its '
                  'currency firms; if they refuse to, a ceasefire on paper is not yet '
                  'trusted where money is at stake.'),
        'regional': ('Neighbours share the risk premium: a war priced as lasting raises '
                     'their costs too.'),
        'global': ('Oil is the gauge the world feels: a war premium in oil is paid at '
                   'every petrol pump.'),
        'economy': ('Markets often price a settlement before it is signed, or refuse to '
                    'price one after it is signed. The gap between the two is the finding.'),
    },
    'fragility': {
        'name': 'Market fragility',
        'plain': ('How dry the forest is, not where the lightning will strike. Asifah '
                  'checks ten conditions that were present before past market collapses '
                  '(expensive shares, a few stocks carrying the index, cheap insurance, '
                  'inverted interest rates, and others) and counts how many are present now.'),
        'local': ('Most of the ten conditions are measured on US markets, so the read is '
                  'first of all about the US stock market.'),
        'regional': ('Other markets follow the US in a sell-off; the more of the world\'s '
                     'markets sit near their highs at once, the less any one can cushion '
                     'another.'),
        'global': ('A fragile market turns an ordinary shock -- a war, a default, a '
                   'policy mistake -- into a larger one.'),
        'economy': ('A drawdown hits pensions, borrowing costs and spending; it is how a '
                    'market problem becomes an economic one.'),
    },
    'analog': {
        'name': 'Historical analog',
        'plain': ('A past market episode whose warning conditions look like today\'s. The '
                  'percentage is the share of conditions the two have in common, not the '
                  'chance that history repeats.'),
        'local': '',
        'regional': '',
        'global': '',
        'economy': ('An analog tells you what the chain of events was last time and how '
                    'long it took. It does not tell you that the chain will run again.'),
    },
    'standing_watch': {
        'name': 'Standing watch',
        'plain': ('A structural exposure that is always there (for example, a country that '
                  'depends on one route for its exports). It is shown so the reader knows '
                  'it exists, but it is not news unless something presses on it.'),
        'local': '', 'regional': '', 'global': '', 'economy': '',
    },
    'commodity_pressure': {
        'name': 'Commodity pressure',
        'plain': ('How heavy and how serious the reporting about a commodity is this scan: '
                  'supply problems, export bans, price swings. It measures the news, not the '
                  'price; the price line is read separately.'),
        'local': 'Producers and importers of the commodity are named in each card.',
        'regional': '', 'global': '',
        'economy': ('Reporting usually moves before prices settle: heavy pressure with a '
                    'flat price means worry without (yet) a shortage.'),
    },
}


# ════════════════════════════════════════════════════════════════════════
# CHOKEPOINTS -- what flows through each, and who feels it
# ════════════════════════════════════════════════════════════════════════
# Structure only. 'verified': False = Claude research awaiting Rachel's pass.

CHOKEPOINTS = {
    'hormuz': {
        'name': 'Strait of Hormuz',
        'plain': ('The only sea exit from the Persian Gulf, between Iran and Oman. Roughly a '
                  'fifth of the oil the world uses each day, and about a fifth of the world\'s '
                  'liquefied natural gas (mostly from Qatar), pass through it.'),
        'local': ('Iraq, Kuwait, Qatar and Bahrain have no other way to ship most of their '
                  'oil and gas. Saudi Arabia and the UAE have pipelines that bypass the '
                  'strait for part of their exports. Iran can threaten the passage from its '
                  'own coast.'),
        'regional': ('Gulf exporters\' revenue, and the US naval presence in Bahrain, depend '
                     'on it staying open.'),
        'global': ('Most of the crude that passes goes to Asia -- China, India, Japan and '
                   'South Korea -- so a closure is first an Asian energy emergency, then '
                   'everyone\'s.'),
        'economy': ('Even a threat raises tanker insurance and freight rates; a closure '
                    'would be among the largest oil-supply shocks on record, felt in fuel '
                    'prices, inflation and interest rates.'),
        'basis': 'EIA, 2024 flow estimates (~20 million barrels a day)',
        'verified': False,
    },
    'bab_el_mandeb': {
        'name': 'Bab el-Mandeb',
        'plain': ('The southern gate of the Red Sea, between Yemen and Djibouti/Eritrea. '
                  'Ships between Asia and Europe pass it on the way to the Suez Canal.'),
        'local': ('Houthi forces in Yemen can reach the passage with missiles and drones, '
                  'as they did from late 2023.'),
        'regional': ('When ships avoid the Red Sea, Egypt loses Suez Canal income, one of '
                     'its largest sources of foreign currency (it fell by more than half in '
                     '2024).'),
        'global': ('The detour around Africa adds roughly 10-14 days to an Asia-Europe '
                   'voyage.'),
        'economy': ('Longer voyages tie up ships and containers, which lifts freight rates '
                    'well beyond the Red Sea itself.'),
        'basis': 'EIA / Suez Canal Authority reporting, 2023-2024',
        'verified': False,
    },
    'suez': {
        'name': 'Suez Canal',
        'plain': ('Egypt\'s canal joining the Red Sea to the Mediterranean; the short route '
                  'between Asia and Europe, carrying around a tenth of world trade in normal '
                  'years.'),
        'local': 'Canal fees are a pillar of Egypt\'s foreign-currency income.',
        'regional': ('Disruption here pushes Europe-Asia trade around Africa and starves '
                     'Mediterranean ports of transit cargo.'),
        'global': 'Europe\'s energy and goods imports from Asia and the Gulf use it.',
        'economy': 'Closure raises freight costs and delivery times for European importers.',
        'basis': 'Suez Canal Authority / UNCTAD, approximate share',
        'verified': False,
    },
    'taiwan_strait': {
        'name': 'Taiwan Strait',
        'plain': ('The water between China and Taiwan, a main shipping lane between North '
                  'and South-East Asia. Taiwan makes most of the world\'s most advanced '
                  'computer chips.'),
        'local': ('Chinese military pressure here tests Taiwan\'s defences and the patience '
                  'of its voters and government.'),
        'regional': ('Japan, South Korea and the Philippines sit beside the lane; their trade '
                     'and US alliance commitments are directly involved.'),
        'global': ('A blockade or conflict would be a great-power crisis between the US and '
                   'China.'),
        'economy': ('Phones, cars, data centres and AI hardware all depend on Taiwanese '
                    'chips; there is no quick substitute.'),
        'basis': 'Industry estimates of leading-edge chip share',
        'verified': False,
    },
    'south_china_sea': {
        'name': 'South China Sea',
        'plain': ('The sea bordered by China, Vietnam, the Philippines, Malaysia, Brunei and '
                  'Taiwan, carrying a large share of world shipping (estimates run from a '
                  'fifth to a third). China claims most of it; an international tribunal '
                  'rejected that claim in 2016.'),
        'local': ('Philippine and Vietnamese fishing boats and resupply missions are the '
                  'usual targets of Chinese coast-guard pressure.'),
        'regional': ('Every South-East Asian economy trades through it; the US-Philippines '
                     'defence treaty can be drawn in by an armed attack on Philippine '
                     'forces or vessels.'),
        'global': ('Freedom of navigation here is a test of whether rules or force decide '
                   'who uses international waters.'),
        'economy': ('Energy for Japan, South Korea and China, and manufactured exports from '
                    'the whole region, pass through it.'),
        'basis': 'CSIS ChinaPower / UNCTAD estimates; 2016 arbitral award',
        'verified': False,
    },
    'luzon_strait': {
        'name': 'Luzon Strait / Bashi Channel',
        'plain': ('The gap between Taiwan and the northern Philippines, the main door between '
                  'the South China Sea and the Pacific.'),
        'local': ('A Taiwan crisis would reach Philippine islands here; US forces have '
                  'access to nearby Philippine bases.'),
        'regional': 'Chinese naval traffic to the Pacific passes through it.',
        'global': ('Undersea data cables linking East Asia run through the area, so damage '
                   'is felt far beyond it.'),
        'economy': 'An alternative lane for regional shipping if the Taiwan Strait is closed.',
        'basis': 'Claude research',
        'verified': False,
    },
    'malacca': {
        'name': 'Strait of Malacca',
        'plain': ('The narrow passage between Malaysia, Singapore and Indonesia; the shortest '
                  'sea route between the Indian Ocean and the Pacific.'),
        'local': ('Singapore\'s port, and Malaysia and Indonesia, live on the traffic and '
                  'police it together.'),
        'regional': ('Most of the Gulf oil bound for China, Japan and South Korea passes '
                     'through it.'),
        'global': ('Chinese planners call their dependence on it the "Malacca dilemma"; it is '
                   'one reason for China\'s overland pipelines and ports abroad.'),
        'economy': ('A closure would push tankers to longer Indonesian routes and raise Asian '
                    'energy costs.'),
        'basis': 'EIA world oil transit chokepoints',
        'verified': False,
    },
    'sunda_strait': {
        'name': 'Sunda Strait',
        'plain': ('The passage between Sumatra and Java in Indonesia, a back-up route if '
                  'Malacca is blocked.'),
        'local': 'Indonesian waters; shallow and difficult for the largest ships.',
        'regional': 'Pressure here matters mainly if Malacca is already in trouble.',
        'global': '', 'economy': 'Using it adds time and cost compared with Malacca.',
        'basis': 'Claude research', 'verified': False,
    },
    'bosporus': {
        'name': 'Turkish Straits (Bosporus and Dardanelles)',
        'plain': ('The only sea route between the Black Sea and the Mediterranean, through '
                  'Istanbul. A 1936 treaty, the Montreux Convention, lets Turkey restrict '
                  'warships passing in wartime.'),
        'local': 'Turkey controls the passage, which gives Ankara leverage over both Russia and NATO.',
        'regional': ('Russia, Ukraine, Romania, Bulgaria and Georgia need it for their sea '
                     'trade.'),
        'global': 'Black Sea grain and Russian oil exports reach world markets through it.',
        'economy': 'Delays here show up in wheat and oil prices.',
        'basis': 'Montreux Convention (1936)', 'verified': False,
    },
    'black_sea': {
        'name': 'Black Sea',
        'plain': ('The sea between Russia, Ukraine, Turkey, Romania, Bulgaria and Georgia. '
                  'Russia and Ukraine together supply roughly a quarter to a third of the '
                  'world\'s wheat exports, much of it shipped from here.'),
        'local': 'Ukraine\'s economy depends on its ports staying usable under Russian attack.',
        'regional': ('NATO members Romania, Bulgaria and Turkey border it; incidents at sea '
                     'risk drawing them in.'),
        'global': ('Importers in Egypt, Lebanon, Syria and across Africa rely on Black Sea '
                   'wheat.'),
        'economy': ('Attacks on ports or grain ships raise bread costs in importing countries, '
                    'where bread prices are politically sensitive.'),
        'basis': 'USDA / FAO export shares, approximate', 'verified': False,
    },
    'gibraltar': {
        'name': 'Strait of Gibraltar',
        'plain': 'The western entrance to the Mediterranean, between Spain and Morocco.',
        'local': 'Spain, Morocco and the UK (Gibraltar) share the waters.',
        'regional': 'All Mediterranean trade with the Atlantic passes it.',
        'global': 'The Atlantic end of the Asia-Suez-Europe route.',
        'economy': 'Rarely contested; trouble here would be unusual and significant.',
        'basis': 'Claude research', 'verified': False,
    },
    'sicily_strait': {
        'name': 'Strait of Sicily',
        'plain': 'The passage between Sicily and Tunisia, linking the eastern and western Mediterranean.',
        'local': 'A main route for migrant boats from North Africa to Italy.',
        'regional': 'Undersea gas pipelines and cables from North Africa cross it.',
        'global': '', 'economy': 'Algerian and Libyan gas to Italy crosses here.',
        'basis': 'Claude research', 'verified': False,
    },
    'mediterranean': {
        'name': 'Eastern Mediterranean',
        'plain': ('The sea off Israel, Lebanon, Syria, Cyprus, Turkey and Egypt, with '
                  'offshore gas fields and the approach to the Suez Canal.'),
        'local': 'Israeli, Egyptian and Cypriot gas fields sit offshore.',
        'regional': ('Russian, Turkish, NATO and Israeli navies operate in the same waters; '
                     'maritime borders are disputed.'),
        'global': 'Gas from here is part of Europe\'s plan to reduce reliance on Russia.',
        'economy': 'Disruption touches regional gas supply and Suez-bound shipping.',
        'basis': 'Claude research', 'verified': False,
    },
    'baltic': {
        'name': 'Baltic Sea approaches',
        'plain': ('The narrow Danish straits leading into the Baltic, ringed by NATO members '
                  'and Russia\'s St Petersburg and Kaliningrad.'),
        'local': ('Russia exports oil from its Baltic ports, much of it on ageing tankers '
                  'outside Western insurance (the "shadow fleet").'),
        'regional': ('Undersea cables and pipelines between NATO states have been damaged '
                     'in suspected sabotage since 2022.'),
        'global': 'A NATO-Russia incident here would involve the alliance directly.',
        'economy': 'Russian oil revenue and Nordic-Baltic energy links run through it.',
        'basis': 'Claude research', 'verified': False,
    },
    'arctic': {
        'name': 'Arctic / Greenland-Iceland-UK gap',
        'plain': ('The sea gap between Greenland, Iceland and the UK that Russia\'s Northern '
                  'Fleet must pass to reach the Atlantic, plus the opening Arctic routes.'),
        'local': ('Greenland\'s strategic value -- bases, minerals, sea lanes -- is why it '
                  'draws US attention.'),
        'regional': 'NATO watches Russian submarines here.',
        'global': ('Melting ice is opening shipping routes and resource claims among Russia, '
                   'the US, Canada and the Nordics, with China calling itself a "near-Arctic" state.'),
        'economy': 'Arctic routes could shorten Europe-Asia shipping in summer.',
        'basis': 'Claude research', 'verified': False,
    },
    'bering_strait': {
        'name': 'Bering Strait',
        'plain': ('The narrow passage between Alaska and Russia, the Pacific door to the '
                  'Arctic.'),
        'local': 'The US and Russia are about 80 km apart here.',
        'regional': 'Russian and Chinese ships use it to reach the Arctic.',
        'global': 'A growing Arctic shipping and military route.', 'economy': '',
        'basis': 'Claude research', 'verified': False,
    },
    'panama_canal': {
        'name': 'Panama Canal',
        'plain': ('The canal across Panama joining the Atlantic and Pacific; around 5% of '
                  'world sea trade, including much of US trade with Asia and South American '
                  'exports.'),
        'local': ('Panama runs it and earns heavily from it; drought in 2023-24 cut daily '
                  'crossings because the canal runs on rain-fed lake water.'),
        'regional': ('US politics over who controls the canal, and Chinese-linked port '
                     'operators at both ends, make it a US-China question.'),
        'global': ('If it is disrupted, the back-up routes are the Strait of Magellan and '
                   'Cape Horn, far to the south, or the US rail network.'),
        'economy': ('Fewer crossings raise freight costs for US grain and gas exports to '
                    'Asia.'),
        'basis': 'Panama Canal Authority / UNCTAD, approximate', 'verified': False,
    },
    'magellan': {
        'name': 'Strait of Magellan',
        'plain': ('The passage at the southern tip of South America, in Chilean waters; the '
                  'fallback route when the Panama Canal is closed or congested.'),
        'local': 'Chile controls it; Argentina\'s Falklands claim sits nearby.',
        'regional': 'Matters mostly when Panama is in trouble.',
        'global': '', 'economy': 'Using it adds thousands of kilometres to a voyage.',
        'basis': 'Claude research', 'verified': False,
    },
    'caribbean': {
        'name': 'Caribbean Basin / Florida Straits',
        'plain': ('The waters between the US, Cuba, Venezuela, Colombia and Central America, '
                  'carrying US Gulf energy exports and the approaches to the Panama Canal.'),
        'local': ('US naval and counter-narcotics operations, Venezuela and Cuba make it the '
                  'most militarised water in the Americas.'),
        'regional': ('Migration, drug routes and Russian or Chinese naval visits to Cuba and '
                     'Venezuela all play out here.'),
        'global': '', 'economy': ('US Gulf oil, gas and grain exports start their voyages '
                                  'here.'),
        'basis': 'Claude research', 'verified': False,
    },
}


def chokepoint_meaning(cp_id):
    """Meaning record for a chokepoint id, or a generic one (never None)."""
    rec = CHOKEPOINTS.get(cp_id)
    if rec:
        return dict(rec)
    g = dict(TERMS['chokepoint'])
    g['name'] = (cp_id or '').replace('_', ' ').title()
    g['basis'] = 'generic definition'
    g['verified'] = True
    return g


# ════════════════════════════════════════════════════════════════════════
# MARKET -- conflict-repricing states, fragility, analogs
# ════════════════════════════════════════════════════════════════════════

REPRICING_STATE_MEANING = {
    'offramp_corroborated': ('A peace track is on the table and the money agrees: shares '
                             'up, currency firmer, defence stocks lagging, oil softer. '
                             'Investors are pricing the deal as one that will hold.'),
    'offramp_contradicted': ('A peace track is on the table but the money refuses it: the '
                             'gauges are moving the way they do when traders expect the '
                             'fighting to go on. Either the deal is not trusted, or the '
                             'threat is seen as bigger than the deal.'),
    'offramp_market_mixed': ('A peace track is on the table and the gauges disagree with each '
                             'other. No clear verdict from the money yet.'),
    'escalation_repricing': ('No peace track, and the gauges are moving together the way they '
                             'do when traders price a widening war.'),
    'calm_repricing': ('No formal peace track, yet the gauges are pricing less war risk -- '
                       'the money is calmer than the diplomacy.'),
    'no_read': 'The gauges did not move together; no verdict this cycle.',
    'insufficient_data': 'Not enough live market prices this cycle to read the gauges.',
    'numb': ('A provocation happened and none of the gauges moved. The market has learned to '
             'ignore this kind of event -- which also means the provoker is not getting the '
             'attention it is trying to buy.'),
    'market_alert': ('A provocation happened and the gauges moved together. The market treated '
                     'it as a change, not as routine.'),
    'partial_flinch': ('A provocation happened and some gauges moved but not all: a flinch, '
                       'not a repricing.'),
    'unattributed_move': ('The gauges moved, but no provocation was recorded; something else '
                          'is moving these markets.'),
    'quiet': 'No provocation and no coherent movement. Baseline.',
    'rhetoric_pending': ('The rhetoric reading this market is compared against was not '
                         'available, so no verdict. Missing, not calm.'),
}

REPRICING_THEATRES = {
    'israel': {
        'name': 'Israel / US-Iran off-ramp',
        'local': ('Israeli shares and the shekel price the war\'s cost to Israel\'s economy '
                  'and borrowing.'),
        'regional': ('A trusted off-ramp lowers the risk premium on Gulf and Levant assets; a '
                     'refused one keeps it.'),
        'global': 'Oil carries the Gulf war premium that every importer pays.',
        'economy': 'Defence stocks against the market show whether investors expect more war spending.',
    },
    'europe_ukraine': {
        'name': 'Europe / Russia-Ukraine off-ramp',
        'local': 'European shares and the euro price the war\'s drag on Europe.',
        'regional': ('European defence stocks show whether rearmament is priced as permanent, '
                     'with or without a truce.'),
        'global': 'Oil and gas prices carry the Russia-sanctions premium.',
        'economy': 'A trusted truce would lower European energy and borrowing costs.',
    },
    'korea': {
        'name': 'Korea / North Korean provocations',
        'local': ('South Korean shares and the won price the risk from the North; for years '
                  'they have barely reacted.'),
        'regional': ('A yen rally (money fleeing to safety) means the market sees risk beyond '
                     'Korea.'),
        'global': 'Korean chipmakers are part of the world\'s electronics supply chain.',
        'economy': 'A market that stops reacting can be surprised harder when it finally does.',
    },
}


def repricing_meaning(theater, state):
    th = REPRICING_THEATRES.get(theater) or {}
    out = {'name': th.get('name') or (theater or '').replace('_', ' ').title(),
           'plain': REPRICING_STATE_MEANING.get(state) or 'No reading.',
           'term': TERMS['conflict_repricing']['plain']}
    for k in ('local', 'regional', 'global', 'economy'):
        out[k] = th.get(k) or TERMS['conflict_repricing'].get(k, '')
    out['basis'] = 'Asifah method definition'
    out['verified'] = True
    return out


# ════════════════════════════════════════════════════════════════════════
# COMMODITY CONVERGENCES -- read Rachel's registry, don't duplicate it
# ════════════════════════════════════════════════════════════════════════

_LABEL_RX = re.compile(r'\b([A-Z][A-Z /\-]{3,40}):\s*')


def split_labelled(text):
    """'STRUCTURAL READOUT: a. WHAT IT MEANS: b. Watch: c' -> {label: text}.

    Labels are the registry's own upper-case headings; 'Watch:' (mixed case)
    is the registry convention for the watch list and is split out too.
    Text before the first label goes under ''."""
    text = ' '.join(str(text or '').split())
    out = {}
    # split off the trailing "Watch: ..." first (mixed case in the registry)
    m = re.search(r'\bWatch:\s*', text)
    if m:
        out['WATCH'] = text[m.end():].strip()
        text = text[:m.start()].strip()
    parts = _LABEL_RX.split(text)
    if parts and parts[0].strip():
        out[''] = parts[0].strip()
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return out


def _sentences(t, n):
    s = re.split(r'(?<=[.!?])\s+', (t or '').strip())
    return ' '.join(x for x in s[:n] if x)


def registry_meaning(entry):
    """Meaning record for a convergence_registry entry (dict) -- never None.

    plain    = the entry's own 'WHAT IT MEANS' paragraph if it has one, else
               the first two sentences of its readout
    facts    = the entry's 'facts' dict, humanised keys, not_implied split out
    watch    = the entry's own 'Watch:' list
    """
    entry = entry or {}
    parts = split_labelled(entry.get('detail') or '')
    plain = parts.get('WHAT IT MEANS') or ''
    readout = parts.get('STRUCTURAL READOUT') or parts.get('') or ''
    if not plain:
        plain = _sentences(readout, 2)
    facts = {}
    not_implied = ''
    for k, v in (entry.get('facts') or {}).items():
        if k in ('not_implied', 'not_evidence_of'):
            not_implied = str(v)
            continue
        facts[k.replace('_', ' ')] = v if isinstance(v, (int, float)) else str(v)
    return {
        'name': (entry.get('id') or '').replace('_', ' ').title(),
        'plain': plain,
        'readout': readout if readout != plain else '',
        'facts': facts,
        'not_implied': not_implied,
        'watch': parts.get('WATCH', ''),
        'regions': entry.get('regions') or [],
        'basis': "Rachel's convergence registry",
        'verified': True,
    }


def humanise_id(x):
    return (x or '').replace('_', ' ').strip().title()
