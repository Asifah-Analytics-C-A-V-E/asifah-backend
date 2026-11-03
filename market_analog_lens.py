"""
market_analog_lens.py -- Asifah Analytics -- ME backend (Market Watch)
================================================================================
TWO QUESTIONS THE FRAGILITY DETECTOR COULD NOT ANSWER (Rachel, Nov 3 2026)

  1. "When there is a 50%+ match to Black Wednesday -- what aspects of today's
     markets are matching that pattern? In the lead-up, how much time between
     what we see today and that event? What should we understand about the
     effects on local, regional and global stability?"

  2. "Are we ONLY watching US markets vs. the pattern recognition? If the Asian
     markets show signs of strain and pattern matching, we want to catch and
     flag that as well -- as well as other markets vs. other patterns."

PART A -- THE ANALOG LENS (question 1)
  For each matched episode, a DOSSIER: the chain of events with dates, the
  interval between the warning stage and the event, the effects at four
  altitudes, and -- the honesty line -- what the match is NOT (for Black
  Wednesday: the detector's conditions are US-market conditions; the episode
  was a currency-peg break that no US index could show). Then LIVE CHECKS:
  for each step of the old chain, can Asifah see that step today, and is it lit?

PART B -- MARKET-BY-MARKET READS (question 2)
  Every tracked market gets its OWN read from its own index and its own
  currency (monthly closes), on conditions that make sense outside the US:
    fuel    run_up (24m return far above its own history), near_high, calm
            (unusually low volatility), recent_run_up
    stress  drawdown (15%+ off the 24-month high), fx_stress (currency down
            10%+ in 6 months AND unusual for that currency -- so Argentina's
            permanent crawl is not "stress" every month), fx_shock (7%+ in one
            month), fx_surge (currency up 8%+ in 6 months -- the Plaza / carry-
            unwind signature), regional_fx_stress / regional_drawdown (two or
            more markets in the same region at once -- contagion), oil_falling,
            oil_spike
  Each market is matched against EVERY episode's market-level signature, home
  region flagged. A market is FLAGGED when it shares at least half of an
  episode's measurable conditions, at least TWO of them, including at least
  one STRESS condition (bubble-type episodes may match on fuel alone).

HONESTY RULES (same doctrine as the detector)
  * Monthly closes: slow by design. A week-long crisis shows a month later.
  * Peg defence, reserves, bond yields and leverage are NOT visible in index
    and currency prices. Those steps are reported as "not visible", never as
    quiet.
  * Dossier dates and figures are Claude research (verified: False) awaiting
    Rachel's pass. Intervals describe what happened THEN, never a projection.
  * Convergence, not prediction. Not investment advice.

PURE COMPUTATION: takes the detector's `data` dict ({series: {YYYY-MM: value}})
and its matches. No Redis. The only network call is fetch_extra_series(),
used by the detector to add the currencies and three Americas indices.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import statistics
from datetime import datetime, timezone

__version__ = '1.0.0'
DOSSIER_BASIS = 'Claude research, Nov 3 2026 -- dates and figures to verify'

# ════════════════════════════════════════════════════════════════════════
# MARKETS -- index + currency per market
# ════════════════════════════════════════════════════════════════════════
# fx: Yahoo ticker. fx_quote 'usd_per_local' = XXXUSD (rises when local
# strengthens); 'local_per_usd' = USD/XXX (rises when local weakens).
# Series keys already fetched by the detector are reused (n225, hsi, ...).
MARKETS = {
    'n225':    {'name': 'Japan (Nikkei 225)', 'region': 'apac', 'fx': 'JPY=X', 'fx_name': 'yen',
                'fx_quote': 'local_per_usd'},
    'hsi':     {'name': 'Hong Kong (Hang Seng)', 'region': 'apac', 'fx': 'HKD=X', 'fx_name': 'Hong Kong dollar',
                'fx_quote': 'local_per_usd', 'peg': (7.75, 7.85)},
    'kospi':   {'name': 'South Korea (KOSPI)', 'region': 'apac', 'fx': 'KRW=X', 'fx_name': 'won',
                'fx_quote': 'local_per_usd'},
    'sensex':  {'name': 'India (Sensex)', 'region': 'apac', 'fx': 'INR=X', 'fx_name': 'rupee',
                'fx_quote': 'local_per_usd'},
    'dax':     {'name': 'Germany (DAX)', 'region': 'europe', 'fx': 'EURUSD=X', 'fx_name': 'euro',
                'fx_quote': 'usd_per_local'},
    'ftse':    {'name': 'United Kingdom (FTSE 100)', 'region': 'europe', 'fx': 'GBPUSD=X', 'fx_name': 'pound',
                'fx_quote': 'usd_per_local'},
    'ta35':    {'name': 'Israel (TA-35)', 'region': 'me', 'fx': 'ILS=X', 'fx_name': 'shekel',
                'fx_quote': 'local_per_usd'},
    'bovespa': {'name': 'Brazil (Bovespa)', 'region': 'wha', 'fx': 'BRL=X', 'fx_name': 'real',
                'fx_quote': 'local_per_usd'},
    'mxx':     {'name': 'Mexico (IPC)', 'region': 'wha', 'index': '^MXX', 'fx': 'MXN=X', 'fx_name': 'peso',
                'fx_quote': 'local_per_usd'},
    'merval':  {'name': 'Argentina (Merval)', 'region': 'wha', 'index': '^MERV', 'fx': 'ARS=X',
                'fx_name': 'peso', 'fx_quote': 'local_per_usd'},
    'tsx':     {'name': 'Canada (TSX)', 'region': 'wha', 'index': '^GSPTSE', 'fx': 'CAD=X',
                'fx_name': 'Canadian dollar', 'fx_quote': 'local_per_usd'},
}
# Currency-only watch: no index read, but the currency is a crisis gauge.
FX_ONLY = {
    'try': {'name': 'Turkey (lira)', 'region': 'europe', 'fx': 'TRY=X', 'fx_name': 'lira', 'fx_quote': 'local_per_usd'},
    'zar': {'name': 'South Africa (rand)', 'region': 'africa', 'fx': 'ZAR=X', 'fx_name': 'rand', 'fx_quote': 'local_per_usd'},
    'egp': {'name': 'Egypt (pound)', 'region': 'me', 'fx': 'EGP=X', 'fx_name': 'Egyptian pound', 'fx_quote': 'local_per_usd'},
    'cny': {'name': 'China (yuan)', 'region': 'apac', 'fx': 'CNY=X', 'fx_name': 'yuan', 'fx_quote': 'local_per_usd'},
}
REGION_NAMES = {'us': 'United States', 'apac': 'Asia & the Pacific', 'europe': 'Europe', 'me': 'Middle East',
                'wha': 'Western Hemisphere', 'africa': 'Africa'}
EXTRA_TICKERS = dict(
    [('fx_' + k, v['fx']) for k, v in list(MARKETS.items()) + list(FX_ONLY.items())]
    + [(k, v['index']) for k, v in MARKETS.items() if v.get('index')]
    + [('brent', 'BZ=F')])

STRESS = {'drawdown', 'fx_stress', 'fx_shock', 'fx_surge', 'regional_fx_stress',
          'regional_drawdown', 'oil_falling', 'oil_spike', 'peg_edge'}
FUEL = {'run_up', 'near_high', 'calm', 'recent_run_up', 'equity_holding'}

CONDITION_WORDS = {
    'run_up': 'shares have risen far faster than their own history (a parabolic run)',
    'recent_run_up': 'a parabolic run within the last year',
    'near_high': 'shares within 5% of their two-year high',
    'calm': 'unusually calm prices (little protection being bought)',
    'equity_holding': 'shares holding up while the currency is under pressure',
    'drawdown': 'shares 15% or more below their two-year high',
    'fx_stress': 'the currency down sharply over six months, unusually so for it',
    'fx_shock': 'the currency down 7% or more in a single month',
    'fx_surge': 'the currency up sharply over six months (a funding-currency squeeze)',
    'regional_fx_stress': 'two or more currencies in the same region under pressure at once',
    'regional_drawdown': 'two or more stock markets in the same region falling at once',
    'oil_falling': 'oil down 25% or more in six months',
    'oil_spike': 'oil up 40% or more in six months',
    'peg_edge': 'a pegged currency pressed against the weak edge of its band',
}

# ════════════════════════════════════════════════════════════════════════
# EPISODE SIGNATURES (market-level) + DOSSIERS
# ════════════════════════════════════════════════════════════════════════
SIGNATURES = {
    'nikkei_1989':       {'run_up', 'near_high', 'calm'},
    'dotcom_2000':       {'run_up', 'near_high', 'calm'},
    'everything_2021':   {'run_up', 'near_high', 'calm'},
    'plaza_1985':        {'fx_surge', 'run_up'},
    'asia_crisis_1997':  {'fx_stress', 'drawdown', 'regional_fx_stress'},
    'carry_unwind_2024': {'fx_surge', 'drawdown'},
    'china_2015':        {'recent_run_up', 'drawdown', 'fx_stress'},
    'erm_1992':          {'fx_stress', 'equity_holding'},
    'uk_gilt_2022':      {'fx_stress', 'fx_shock', 'equity_holding'},
    'eurozone_2011':     {'drawdown', 'regional_drawdown'},
    'turkey_2018':       {'fx_stress', 'fx_shock', 'drawdown'},
    'asia_ruble_1998':   {'fx_stress', 'drawdown', 'oil_falling'},
    'mexico_1994':       {'fx_stress', 'fx_shock', 'drawdown'},
    'nenegate_2015':     {'fx_shock', 'drawdown'},
    'oil_shock_1973':    {'oil_spike', 'drawdown'},
}
BUBBLE_TYPES = {'nikkei_1989', 'dotcom_2000', 'everything_2021', 'plaza_1985'}

DOSSIERS = {
    'erm_1992': {
        'label': 'ERM crisis / Black Wednesday', 'region': 'europe',
        'chain': [
            ('Oct 1990', 'The UK joins Europe\'s Exchange Rate Mechanism, pegging the pound near 2.95 German marks.'),
            ('1990-92', 'German reunification pushes the Bundesbank to keep rates high; Britain, in recession, imports those rates through the peg.'),
            ('2 Jun 1992', 'Danish voters reject the Maastricht Treaty; markets start doubting the path to monetary union and the pegs that lead to it.'),
            ('Jul-Sep 1992', 'The Bundesbank raises rates again; the pound sits at the bottom of its band and the Bank of England spends reserves defending it.'),
            ('16 Sep 1992', '"Black Wednesday": the UK raises rates from 10% to 12% and announces 15%, then leaves the ERM that evening. Italy suspends the lira the next day.'),
        ],
        'interval_then': ('About 3.5 months from the Danish "no" (2 Jun) to the exit (16 Sep), and about 23 months '
                          'from joining the peg to leaving it. The decisive selling took days.'),
        'effects': {
            'local': 'The pound fell about 15% against the mark within weeks; the government\'s economic credibility collapsed, though cheaper money then helped the UK recover.',
            'regional': 'The ERM crisis rolled on into 1993, when the bands were widened to 15% -- in effect, pegs gave way to floating within Europe.',
            'global': 'It became the template for speculative attacks on fixed currencies, and the case study for why markets test a peg when domestic needs and the peg diverge.',
            'economy': 'The stock market barely flinched -- the FTSE recovered within months. The damage was in the currency, rates and political credibility, not in shares.',
        },
        'not': ('Asifah\'s US-built conditions cannot see a currency peg. A match to Black Wednesday on those '
                'conditions means US markets resemble mid-1992, not that a peg is under attack. The market-by-market '
                'reads below are where a Black Wednesday-shaped event would show: a currency falling sharply while '
                'its stock market holds.'),
        'live_checks': [
            ('A currency under sharp pressure while its stock market holds', {'fx_stress', 'equity_holding'}),
            ('A pegged currency pressed against the weak edge of its band', {'peg_edge'}),
            ('A central bank spending reserves or raising rates to defend a peg', None),
            ('A political shock that puts the commitment to the peg in doubt', None),
        ],
    },
    'mexico_1994': {
        'label': 'Mexican peso / Tequila crisis', 'region': 'wha',
        'chain': [
            ('1 Jan 1994', 'NAFTA takes effect and the Zapatista uprising begins in Chiapas.'),
            ('23 Mar 1994', 'Presidential candidate Luis Donaldo Colosio is assassinated; capital starts to leave.'),
            ('1994', 'Mexico swaps peso debt for dollar-linked bonds (tesobonos) and spends reserves holding the peso band.'),
            ('20-22 Dec 1994', 'The peso is devalued, then floated; it loses about half its value within months.'),
            ('Jan-Feb 1995', 'A US-IMF rescue of about $50 billion; contagion hits Argentina and other emerging markets.'),
        ],
        'interval_then': 'About 9 months from the Colosio assassination to the devaluation; the collapse itself took days.',
        'effects': {
            'local': 'Mexico\'s economy shrank by roughly 6% in 1995; a banking crisis followed.',
            'regional': 'Argentina suffered a bank run in 1995 (the "Tequila effect"); Latin American assets repriced together.',
            'global': 'The first modern case of one mid-size emerging market repricing all the others, and of a US-led rescue.',
            'economy': 'Dollar-linked short-term debt turned a currency fall into a solvency problem.',
        },
        'not': ('Asifah cannot see reserves or the maturity of a country\'s dollar debt. A Tequila-shaped read here means '
                'a currency and stock market falling together, not proof of the debt structure that made 1994 so severe.'),
        'live_checks': [
            ('An emerging-market currency and stock market falling together', {'fx_stress', 'drawdown'}),
            ('A sudden one-month currency drop', {'fx_shock'}),
            ('A second market in the same region following', {'regional_fx_stress'}),
            ('Reserves draining to hold a currency band', None),
        ],
    },
    'asia_crisis_1997': {
        'label': 'Asian financial crisis', 'region': 'apac',
        'chain': [
            ('1996', 'Thailand runs a current-account deficit near 8% of GDP; banks fund property lending with dollar loans.'),
            ('May 1997', 'Speculative attacks on the baht; the Bank of Thailand burns reserves defending it.'),
            ('2 Jul 1997', 'Thailand floats the baht; it loses about half its value in six months.'),
            ('Jul-Aug 1997', 'The Philippines, Malaysia and Indonesia let their currencies go.'),
            ('Dec 1997', 'South Korea takes an IMF package of about $57 billion.'),
            ('May 1998', 'Indonesia\'s President Suharto resigns amid riots.'),
        ],
        'interval_then': ('About 7 weeks from the main speculative attacks to the baht float, but 12-18 months from the '
                          'visible warning signs (deficits, empty office towers) to the break.'),
        'effects': {
            'local': 'Indonesia\'s economy shrank by about 13% in 1998; Thailand and South Korea went into deep recessions.',
            'regional': 'Contagion ran by vulnerability, not geography: economies with similar dollar borrowing fell in turn.',
            'global': 'It fed into Russia\'s 1998 default and the near-collapse of the hedge fund LTCM.',
            'economy': 'Political change followed economic collapse: Suharto fell, Korea\'s politics and conglomerates were reshaped.',
        },
        'not': ('Asifah sees currencies and stock indices, not reserves, current accounts or dollar borrowing. It can show '
                'several Asian currencies falling together; it cannot show why.'),
        'live_checks': [
            ('Several currencies in the same region falling at once', {'regional_fx_stress'}),
            ('A currency and stock market falling together', {'fx_stress', 'drawdown'}),
            ('A pegged currency pressed against its band', {'peg_edge'}),
            ('Reserves draining at a central bank defending a peg', None),
        ],
    },
    'carry_unwind_2024': {
        'label': 'Yen carry-trade unwind', 'region': 'apac',
        'chain': [
            ('2022-24', 'Near-zero Japanese rates make the yen the world\'s cheapest currency to borrow and invest elsewhere.'),
            ('31 Jul 2024', 'The Bank of Japan raises rates; the yen starts to strengthen.'),
            ('2 Aug 2024', 'Weak US jobs data hits global risk appetite.'),
            ('5 Aug 2024', 'The Nikkei falls about 12% in one day as borrowed-yen positions are unwound worldwide; most of the fall reverses within weeks.'),
        ],
        'interval_then': 'Days: about a week from the rate rise to the crash day.',
        'effects': {
            'local': 'Japan\'s market had its worst day since 1987, then recovered most of the loss.',
            'regional': 'Taiwan and Korea fell sharply the same day.',
            'global': 'Selling spread to unrelated markets because the borrowed money had to be repaid.',
            'economy': 'A domestic policy move in one country became a global volatility event within days.',
        },
        'not': 'Asifah cannot see how much money is borrowed in yen; it sees the signature -- a rising yen with falling shares.',
        'live_checks': [
            ('A funding currency surging while its stock market falls', {'fx_surge', 'drawdown'}),
            ('Falls spreading to other markets in the region', {'regional_drawdown'}),
            ('The size of borrowed-currency positions', None),
        ],
    },
    'plaza_1985': {
        'label': 'Plaza Accord -> Japanese asset bubble', 'region': 'apac',
        'chain': [
            ('22 Sep 1985', 'The G5 agree at the Plaza Hotel to push the dollar down.'),
            ('1986-87', 'The yen roughly doubles against the dollar; the Bank of Japan cuts rates to a postwar low to cushion exporters.'),
            ('Feb 1987', 'The Louvre Accord tries to stop the dollar\'s fall; Japan keeps rates low.'),
            ('29 Dec 1989', 'The Nikkei peaks near 38,900 after tripling.'),
        ],
        'interval_then': 'About 4 years from the currency agreement to the market peak.',
        'effects': {
            'local': 'The bubble was the policy response to the currency move; its bursting began Japan\'s "lost decades".',
            'regional': 'Japanese money flowed across Asia during the boom.',
            'global': 'A lesson that coordinated currency moves can create the next bubble elsewhere.',
            'economy': 'Cheap money moved into property and shares, not into the export economy it was meant to protect.',
        },
        'not': 'A currency surge today is not a policy decision; Asifah cannot see whether a central bank is easing to fight it.',
        'live_checks': [
            ('A currency surging sharply', {'fx_surge'}),
            ('Shares in a parabolic run at the same time', {'run_up'}),
            ('A central bank easing to fight a strong currency', None),
        ],
    },
    'nikkei_1989': {
        'label': 'Nikkei peak / Lost Decades', 'region': 'apac',
        'chain': [
            ('1987-89', 'Japanese shares and land prices soar on cheap credit.'),
            ('May 1989', 'The Bank of Japan begins raising rates.'),
            ('29 Dec 1989', 'The Nikkei peaks; it falls about 63% by August 1992.'),
            ('1990s', 'Banks carry bad property loans for a decade; deflation sets in.'),
        ],
        'interval_then': 'About 7 months from the first rate rise to the peak; 34 years to regain the 1989 high.',
        'effects': {
            'local': 'A decade of stagnation and a banking crisis.',
            'regional': 'Japanese lending to Asia slowed.',
            'global': 'The case study for a bubble whose burst is a long stagnation, not a quick crash.',
            'economy': 'Balance-sheet repair kept growth and prices low for a generation.',
        },
        'not': 'A bubble-shaped market is fuel, not a trigger; the Nikkei peaked only after policy tightened.',
        'live_checks': [
            ('A parabolic run near the highs with calm prices', {'run_up', 'near_high', 'calm'}),
            ('Central-bank tightening into the run', None),
        ],
    },
    'china_2015': {
        'label': 'China deval / yuan shock', 'region': 'apac',
        'chain': [
            ('Jun 2014-Jun 2015', 'Shanghai shares more than double on borrowed money.'),
            ('12 Jun 2015', 'The Shanghai market peaks and then crashes despite state buying.'),
            ('11 Aug 2015', 'China devalues the yuan by about 2% in a surprise move.'),
            ('24 Aug 2015', 'Global markets fall sharply ("China\'s Black Monday").'),
        ],
        'interval_then': 'About 2 months from the Shanghai peak to the devaluation; 2 weeks from the devaluation to the global sell-off.',
        'effects': {
            'local': 'Capital left China; Beijing spent hundreds of billions of dollars of reserves steadying the yuan.',
            'regional': 'Asian currencies and commodity exporters weakened with China\'s demand.',
            'global': 'US shares fell about 12%; the Fed delayed its first rate rise.',
            'economy': 'Commodity prices fell on fears for Chinese demand.',
        },
        'not': 'Asifah reads the yuan and Hong Kong, not mainland capital controls or reserves.',
        'live_checks': [
            ('A recent run-up followed by a sharp fall', {'recent_run_up', 'drawdown'}),
            ('The yuan or a regional currency weakening sharply', {'fx_stress'}),
        ],
    },
    'eurozone_2011': {
        'label': 'Eurozone sovereign debt crisis', 'region': 'europe',
        'chain': [
            ('May 2010', 'Greece receives its first bailout.'),
            ('2011', 'Doubts spread to Portugal, Ireland, Spain and Italy; banks holding their bonds are repriced.'),
            ('Nov 2011', 'Greek and Italian governments change under market pressure.'),
            ('26 Jul 2012', 'ECB President Draghi pledges "whatever it takes"; spreads fall before a bond is bought.'),
        ],
        'interval_then': 'About 2 years from the first bailout to the turning point.',
        'effects': {
            'local': 'Greece lost about a quarter of its output; unemployment passed 25%.',
            'regional': 'The crisis spread across a shared currency with no shared budget.',
            'global': 'European banks pulled back lending worldwide.',
            'economy': 'A loop between weak governments and the banks holding their debt.',
        },
        'not': 'Asifah does not read government bond spreads, the core of this episode.',
        'live_checks': [
            ('Several European markets falling together', {'regional_drawdown'}),
            ('Government bond spreads widening', None),
        ],
    },
    'turkey_2018': {
        'label': 'Turkish lira crisis', 'region': 'europe',
        'chain': [
            ('Early 2018', 'Turkish companies carry large dollar debts; inflation rises.'),
            ('Spring 2018', 'The central bank resists raising rates under political pressure.'),
            ('1-10 Aug 2018', 'US sanctions on two ministers and doubled steel tariffs; the lira falls about 20% in a week.'),
            ('13 Sep 2018', 'The central bank raises rates to 24%.'),
        ],
        'interval_then': 'About 3 months of steady decline before the August collapse; 5 weeks from the collapse to the rate rise.',
        'effects': {
            'local': 'The lira lost about 40% in 2018; inflation passed 20% and the economy fell into recession.',
            'regional': 'European banks with Turkish loans fell; other emerging currencies weakened briefly.',
            'global': 'A case where politics amplified rather than absorbed a currency shock.',
            'economy': 'Dollar debts became heavier as the lira fell.',
        },
        'not': 'Asifah reads the lira price, not company dollar debt or central-bank independence.',
        'live_checks': [
            ('A currency falling sharply, including a one-month drop', {'fx_stress', 'fx_shock'}),
            ('Policy refusing to respond (rates held into the fall)', None),
        ],
    },
    'uk_gilt_2022': {
        'label': 'UK gilt / LDI crisis', 'region': 'europe',
        'chain': [
            ('23 Sep 2022', 'The "mini-budget" announces unfunded tax cuts.'),
            ('26 Sep 2022', 'The pound hits a record low against the dollar; long-term gilt yields jump.'),
            ('28 Sep 2022', 'Pension funds face collateral calls; the Bank of England starts emergency bond buying.'),
            ('20 Oct 2022', 'Prime Minister Truss resigns.'),
        ],
        'interval_then': 'Days: five days from the budget to the Bank of England\'s intervention; four weeks to the resignation.',
        'effects': {
            'local': 'Mortgage rates jumped; a prime minister fell within weeks.',
            'regional': 'Limited spillover; it was a British credibility shock.',
            'global': 'A warning that hidden leverage in "safe" pension strategies can force a central bank to act.',
            'economy': 'The pound and gilts moved; the FTSE 100, full of overseas earners, held up.',
        },
        'not': 'Asifah does not read gilt yields or pension leverage, the heart of this episode.',
        'live_checks': [
            ('A currency shock while shares hold', {'fx_shock', 'equity_holding'}),
            ('Government bond yields jumping', None),
        ],
    },
    'asia_ruble_1998': {
        'label': 'Russian default / ruble devaluation', 'region': 'europe',
        'chain': [
            ('Late 1997-1998', 'Oil falls toward $11 a barrel after the Asian crisis; Russia\'s budget depends on it.'),
            ('Jul 1998', 'An IMF package of about $22.6 billion fails to restore confidence.'),
            ('17 Aug 1998', 'Russia devalues the ruble and defaults on its domestic debt.'),
            ('23 Sep 1998', 'The New York Fed organises a rescue of the hedge fund LTCM.'),
        ],
        'interval_then': 'About 4 weeks from the IMF package to the default; 5 weeks from the default to the LTCM rescue.',
        'effects': {
            'local': 'The ruble lost about two-thirds of its value; savings were wiped out.',
            'regional': 'Former Soviet economies were hit through trade and banks.',
            'global': 'A leveraged US fund nearly failed; the Fed cut rates three times.',
            'economy': 'A commodity exporter\'s collapse reached Wall Street through leverage.',
        },
        'not': 'Asifah does not read Russian markets directly here; oil is the visible link.',
        'live_checks': [
            ('Oil falling sharply', {'oil_falling'}),
            ('A commodity exporter\'s currency and shares falling together', {'fx_stress', 'drawdown'}),
            ('Leverage at funds abroad', None),
        ],
    },
    'nenegate_2015': {
        'label': 'South Africa "Nenegate"', 'region': 'africa',
        'chain': [
            ('9 Dec 2015', 'President Zuma fires Finance Minister Nene and appoints a little-known MP.'),
            ('10-11 Dec 2015', 'The rand falls about 10%; bank shares drop about 20%.'),
            ('13 Dec 2015', 'Zuma reverses course and appoints Pravin Gordhan; most of the move reverses.'),
        ],
        'interval_then': 'Days: four days from the firing to the reversal.',
        'effects': {
            'local': 'A political decision repriced the country within hours.',
            'regional': 'Little spillover.',
            'global': 'A clean example of markets pricing institutions rather than fundamentals.',
            'economy': 'Borrowing costs jumped and fell back with the minister.',
        },
        'not': 'A currency shock alone does not say what caused it; the rhetoric layer is where the cause shows.',
        'live_checks': [('A sudden one-month currency drop', {'fx_shock'})],
    },
    'oil_shock_1973': {
        'label': 'OPEC oil embargo', 'region': 'me',
        'chain': [
            ('6 Oct 1973', 'The Yom Kippur War begins.'),
            ('17 Oct 1973', 'Arab oil producers announce an embargo and production cuts.'),
            ('Jan 1974', 'Oil prices have roughly quadrupled.'),
            ('Mar 1974', 'The embargo is lifted; inflation and recession persist.'),
        ],
        'interval_then': 'About 11 days from the war\'s start to the embargo; about 3 months to the full price shock.',
        'effects': {
            'local': 'Producers gained leverage and revenue.',
            'regional': 'The Gulf\'s oil weapon became a permanent part of Middle East politics.',
            'global': 'Western economies entered "stagflation"; the US stock market fell about 48% by October 1974.',
            'economy': 'Energy costs fed inflation, and central banks tightened into a slowing economy.',
        },
        'not': 'Outside Asifah\'s market data, which starts later; it is here as a mechanism.',
        'live_checks': [('Oil up sharply', {'oil_spike'}), ('War in a producing region', None)],
    },
    'black_monday_1987': {
        'label': 'Black Monday', 'region': 'us',
        'chain': [('Aug 1987', 'US shares peak after a strong run.'),
                  ('14-16 Oct 1987', 'Rising rates and trade-deficit news hit markets.'),
                  ('19 Oct 1987', 'The Dow falls 22.6% in a day; automated "portfolio insurance" selling feeds itself.'),
                  ('20 Oct 1987', 'The Fed promises liquidity; markets stabilise.')],
        'interval_then': 'About 2 months from the peak to the crash.',
        'effects': {'local': 'The largest one-day fall in US history.',
                    'regional': 'Markets from Hong Kong to London fell the same week.',
                    'global': 'No recession followed; the Fed\'s quick response became a template.',
                    'economy': 'A market-structure event, not an economic one.'},
        'not': 'A crash driven by trading mechanics; pre-signals were thin.',
        'live_checks': [('Calm prices near highs', {'near_high', 'calm'})],
    },
    'dotcom_2000': {
        'label': 'Dot-com top', 'region': 'us',
        'chain': [('1995-99', 'Internet shares soar; the Nasdaq rises about fivefold.'),
                  ('Jun 1999', 'The Fed starts raising rates.'),
                  ('10 Mar 2000', 'The Nasdaq peaks; it falls about 78% by Oct 2002.')],
        'interval_then': 'About 9 months from the first rate rise to the peak.',
        'effects': {'local': 'A mild US recession in 2001; tech investment collapsed.',
                    'regional': 'European telecom shares collapsed too.',
                    'global': 'The template for a story stock bubble.',
                    'economy': 'Wealth losses concentrated in tech and among savers who bought late.'},
        'not': 'Concentration and a story stock theme are the shared features; the trigger was policy and exhaustion.',
        'live_checks': [('A parabolic run near highs', {'run_up', 'near_high'})],
    },
    'gfc_2008': {
        'label': 'Global Financial Crisis top', 'region': 'us',
        'chain': [('Aug 2007', 'BNP Paribas freezes funds holding US mortgage securities.'),
                  ('9 Oct 2007', 'US shares peak.'),
                  ('Mar 2008', 'Bear Stearns is rescued.'),
                  ('15 Sep 2008', 'Lehman Brothers fails.')],
        'interval_then': 'About 2 months from the first fund freeze to the peak; about 11 months from the peak to Lehman.',
        'effects': {'local': 'US shares fell 57%; millions lost homes and jobs.',
                    'regional': 'European banks holding US mortgage debt were hit hard.',
                    'global': 'The deepest global recession since the 1930s.',
                    'economy': 'Credit froze; governments rescued banks.'},
        'not': 'Asifah reads credit spreads in the US; it cannot see where the bad loans sit.',
        'live_checks': [('Stress in one market while others hold near highs', {'drawdown'})],
    },
    'everything_2021': {
        'label': 'Everything-bubble top', 'region': 'us',
        'chain': [('2020-21', 'Zero rates and stimulus lift nearly every asset.'),
                  ('3 Jan 2022', 'US shares peak.'),
                  ('Mar 2022', 'The Fed begins its fastest rate rises in decades.')],
        'interval_then': 'The peak came about 2 months before the first rate rise.',
        'effects': {'local': 'US shares fell about 25%, the Nasdaq about 33%.',
                    'regional': 'Global bonds and shares fell together.',
                    'global': 'Inflation, not a crash, ended the run.',
                    'economy': 'Mortgage rates doubled; speculative assets collapsed.'},
        'not': 'A rate-cycle top, not a credit crisis.',
        'live_checks': [('A parabolic run near highs with calm prices', {'run_up', 'near_high', 'calm'})],
    },
}


# ════════════════════════════════════════════════════════════════════════
# SERIES MATH
# ════════════════════════════════════════════════════════════════════════
def _months(s):
    return sorted(s.keys()) if s else []


def _ret(s, m_list, i, back):
    if i - back < 0:
        return None
    a, b = s[m_list[i - back]], s[m_list[i]]
    return (b - a) / a if a else None


def _z(v, hist):
    hist = [h for h in hist if h is not None]
    if v is None or len(hist) < 24:
        return None
    sd = statistics.pstdev(hist)
    return (v - statistics.mean(hist)) / sd if sd else None


def _local_ccy(fx_series, quote):
    """Convert to a 'value of the local currency' series (up = stronger)."""
    if not fx_series:
        return None
    if quote == 'usd_per_local':
        return dict(fx_series)
    return {k: (1.0 / v) for k, v in fx_series.items() if v}


def market_conditions(idx, fx_local, brent=None, peg=None, fx_raw=None):
    """Conditions for one market at its latest month.

    Returns (active:set, quiet:set, unmeasured:set, detail:dict)."""
    active, quiet, unmeasured, detail = set(), set(), set(), {}

    def put(name, val):
        if val is None:
            unmeasured.add(name)
        elif val:
            active.add(name)
        else:
            quiet.add(name)

    if idx and len(idx) >= 30:
        ml = _months(idx)
        i = len(ml) - 1
        r24 = [_ret(idx, ml, j, 24) for j in range(24, len(ml))]
        z24 = _z(r24[-1], r24[:-1]) if r24 else None
        put('run_up', (z24 is not None and z24 > 1.5) if z24 is not None else None)
        recent = None
        if len(r24) >= 13:
            zs = [_z(r24[k], r24[:k]) for k in range(len(r24) - 12, len(r24))]
            zs = [x for x in zs if x is not None]
            recent = bool(zs) and max(zs) > 1.5
        put('recent_run_up', recent)
        hi = max(idx[m] for m in ml[-24:])
        last = idx[ml[-1]]
        dd = (last - hi) / hi if hi else 0
        detail['pct_from_24m_high'] = round(dd * 100, 1)
        put('near_high', dd >= -0.05)
        put('drawdown', dd <= -0.15)
        rets = [_ret(idx, ml, j, 1) for j in range(1, len(ml))]
        vols = []
        for j in range(12, len(rets) + 1):
            w = [x for x in rets[j - 12:j] if x is not None]
            if len(w) >= 10:
                vols.append(statistics.pstdev(w))
        if len(vols) >= 60:
            cur = vols[-1]
            rank = sum(1 for v in vols[:-1] if v < cur) / max(1, len(vols) - 1)
            put('calm', rank < 0.2)
            detail['vol_percentile'] = round(rank * 100)
        else:
            unmeasured.add('calm')
        r6 = _ret(idx, ml, i, 6)
        detail['index_6m_pct'] = round(r6 * 100, 1) if r6 is not None else None
        detail['as_of'] = ml[-1]
    else:
        for n in ('run_up', 'recent_run_up', 'near_high', 'drawdown', 'calm'):
            unmeasured.add(n)

    if fx_local and len(fx_local) >= 30:
        fl = _months(fx_local)
        j = len(fl) - 1
        c6 = [_ret(fx_local, fl, k, 6) for k in range(6, len(fl))]
        z6 = _z(c6[-1], c6[-121:-1]) if c6 else None
        c1 = _ret(fx_local, fl, j, 1)
        detail['fx_6m_pct'] = round(c6[-1] * 100, 1) if c6 and c6[-1] is not None else None
        detail['fx_1m_pct'] = round(c1 * 100, 1) if c1 is not None else None
        put('fx_stress', bool(c6 and c6[-1] is not None and c6[-1] <= -0.10 and z6 is not None and z6 <= -1.5)
            if z6 is not None else None)
        put('fx_surge', bool(c6 and c6[-1] is not None and c6[-1] >= 0.08 and z6 is not None and z6 >= 1.5)
            if z6 is not None else None)
        put('fx_shock', (c1 is not None and c1 <= -0.07) if c1 is not None else None)
        detail['fx_as_of'] = fl[-1]
    else:
        for n in ('fx_stress', 'fx_surge', 'fx_shock'):
            unmeasured.add(n)

    if 'drawdown' in active or 'drawdown' in quiet:
        if 'fx_stress' in active or 'fx_shock' in active:
            put('equity_holding', 'drawdown' not in active and (detail.get('index_6m_pct') or 0) > -5)
        else:
            quiet.add('equity_holding')
    else:
        unmeasured.add('equity_holding')

    if peg and fx_raw:
        last = fx_raw[_months(fx_raw)[-1]]
        lo, hi = peg
        put('peg_edge', last >= hi - (hi - lo) * 0.1)
        detail['peg_rate'] = round(last, 4)

    if brent and len(brent) >= 8:
        bl = _months(brent)
        b6 = _ret(brent, bl, len(bl) - 1, 6)
        put('oil_falling', b6 is not None and b6 <= -0.25)
        put('oil_spike', b6 is not None and b6 >= 0.40)
        detail['brent_6m_pct'] = round(b6 * 100, 1) if b6 is not None else None
    else:
        unmeasured.update({'oil_falling', 'oil_spike'})
    return active, quiet, unmeasured, detail


def _similarity(active, sig, measurable):
    """Jaccard over the episode's conditions. A match needs a shared stress
    condition, unless the episode is a bubble type (fuel-only)."""
    # The denominator is the FULL signature: a condition we cannot measure for
    # this market counts against the match (an unmeasured step is not a match),
    # so a currency-only read can never score 100% on half a pattern.
    if not (sig & measurable):
        return 0.0, set()
    shared = active & sig
    union = (active & (STRESS | FUEL)) | sig
    return (len(shared) / len(union) if union else 0.0), shared


def regional_reads(data):
    """Market-by-market reads + flags. Never raises; missing data = unmeasured."""
    out, flags = {}, []
    brent = data.get('brent')
    by_region = {}
    raw = {}
    for key, cfg in list(MARKETS.items()) + list(FX_ONLY.items()):
        try:
            idx = data.get(key) if key in MARKETS else None
            fx_raw = data.get('fx_' + key)
            fx_local = _local_ccy(fx_raw, cfg['fx_quote'])
            a, q, u, det = market_conditions(idx, fx_local, brent, cfg.get('peg'), fx_raw)
            if key in FX_ONLY:
                for n in ('run_up', 'recent_run_up', 'near_high', 'drawdown', 'calm', 'equity_holding'):
                    a.discard(n), q.discard(n)
                    u.add(n)
            raw[key] = (cfg, a, q, u, det)
            by_region.setdefault(cfg['region'], []).append(key)
        except Exception as e:
            raw[key] = (cfg, set(), set(), set(), {'error': str(e)[:120]})

    # regional contagion conditions
    for region, keys in by_region.items():
        fx_hit = [k for k in keys if {'fx_stress', 'fx_shock'} & raw[k][1]]
        dd_hit = [k for k in keys if 'drawdown' in raw[k][1]]
        for k in keys:
            a, q = raw[k][1], raw[k][2]
            if len(keys) >= 2:
                (a if len(fx_hit) >= 2 and k in fx_hit else q).add('regional_fx_stress')
                (a if len(dd_hit) >= 2 and k in dd_hit else q).add('regional_drawdown')
            else:
                raw[k][3].update({'regional_fx_stress', 'regional_drawdown'})

    for key, (cfg, a, q, u, det) in raw.items():
        measurable = (a | q)
        scored = []
        for ep, sig in SIGNATURES.items():
            sim, shared = _similarity(a, sig, measurable)
            if not shared:
                continue
            if not (shared & STRESS) and ep not in BUBBLE_TYPES:
                continue
            if ep in BUBBLE_TYPES and len(shared) < 2:
                continue
            dz = DOSSIERS.get(ep, {})
            scored.append({'episode': ep, 'label': dz.get('label', ep), 'similarity_pct': round(sim * 100),
                           'home_region': dz.get('region') == cfg['region'],
                           'shared': sorted(shared), 'then_only': sorted((sig & measurable) - a),
                           'unmeasured_in_episode': sorted(sig - measurable)})
        scored.sort(key=lambda s: (-s['similarity_pct'], not s['home_region']))
        top = scored[0] if scored else None
        # a flag needs half the pattern AND at least two shared conditions --
        # one lit condition is a reading, not a pattern
        flagged = bool(top and top['similarity_pct'] >= 50 and len(top['shared']) >= 2)
        rec = {
            'name': cfg['name'], 'region': cfg['region'], 'region_name': REGION_NAMES.get(cfg['region']),
            'currency': cfg['fx_name'], 'currency_only': key in FX_ONLY,
            'conditions_now': [{'id': c, 'words': CONDITION_WORDS.get(c, c)} for c in sorted(a)],
            'quiet': sorted(q), 'unmeasured': sorted(u), 'detail': det,
            'closest': scored[:3], 'flagged': flagged,
        }
        if flagged:
            rec['flag_text'] = ('%s: %d%% of the %s pattern\'s measurable conditions -- %s.'
                                % (cfg['name'], top['similarity_pct'], top['label'],
                                   '; '.join(CONDITION_WORDS.get(c, c) for c in top['shared'])))
            flags.append({'market': key, 'name': cfg['name'], 'region': cfg['region'],
                          'episode': top['episode'], 'label': top['label'],
                          'similarity_pct': top['similarity_pct'], 'home_region': top['home_region'],
                          'text': rec['flag_text']})
        out[key] = rec
    flags.sort(key=lambda f: -f['similarity_pct'])
    return {'markets': out, 'flags': flags, 'cadence': 'monthly closes',
            'note': ('Each market is read on its own index and currency. Monthly closes are slow by design; '
                     'peg defence, reserves, bond yields and leverage cannot be seen in these prices and are '
                     'reported as not visible, never as quiet.'),
            'generated_at': datetime.now(timezone.utc).isoformat(), 'version': __version__}


# ════════════════════════════════════════════════════════════════════════
# LENS for the detector's own matches
# ════════════════════════════════════════════════════════════════════════
def analog_lens(matches, reads, backtest=None):
    """One record per matched episode (top 3): chain, interval, effects, what
    the match is not, and live checks against the market-by-market reads."""
    out = []
    leads = {e.get('id'): e for e in (backtest or {}).get('episode_reads', []) if isinstance(e, dict)}
    markets = (reads or {}).get('markets') or {}
    for m in (matches or [])[:3]:
        ep = m.get('id')
        dz = DOSSIERS.get(ep)
        if not dz:
            continue
        checks = []
        for step, need in dz.get('live_checks', []):
            if need is None:
                checks.append({'step': step, 'visible': False, 'lit': None,
                               'evidence': 'Not visible in market prices; Asifah cannot confirm or rule this out.'})
                continue
            hits = [rec['name'] for rec in markets.values()
                    if need <= {c['id'] for c in rec.get('conditions_now', [])}]
            measurable = [rec['name'] for rec in markets.values()
                          if need <= (set(rec.get('quiet', [])) | {c['id'] for c in rec.get('conditions_now', [])})]
            checks.append({'step': step, 'visible': bool(measurable), 'lit': bool(hits),
                           'evidence': (('Lit in: ' + ', '.join(hits[:4])) if hits else
                                        ('Not lit in any of %d markets read' % len(measurable)) if measurable
                                        else 'Not measurable with the data on hand this cycle.')})
        lead = (leads.get(ep) or {}).get('lead_months_at_elevated_plus')
        rec = {
            'id': ep, 'label': dz['label'], 'similarity_pct': m.get('similarity_pct'),
            'chain': ['%s -- %s' % (d, t) for d, t in dz['chain']],
            'interval_then': dz['interval_then'] + (
                ' In Asifah\'s backtest, the US-market conditions read elevated or higher for about %d '
                'months before this episode.' % lead if lead else ''),
            'effects': dz['effects'],
            'what_the_match_is_not': dz['not'],
            'live_checks': checks,
            'basis': DOSSIER_BASIS, 'verified': False,
        }
        out.append(rec)
    return out


def fetch_extra_series(fetch_recent):
    """Fetch the extra currencies/indices with the detector's own Yahoo helper
    (recent window only: ~20 requests, not 60). Returns {key: series}."""
    out = {}
    for key, tk in EXTRA_TICKERS.items():
        try:
            out[key] = fetch_recent(tk)
        except Exception:
            out[key] = None
    return out
