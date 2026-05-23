"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — CONVERGENCE REGISTRY
  v1.1.0 (May 23 2026)
═══════════════════════════════════════════════════════════════════════

Single source of truth for cross-axis / cross-regional convergence narratives.

A "convergence" is a compound risk that emerges only when two or more
otherwise-independent signals fire simultaneously. The textbook example:

  - Country has active humanitarian crisis (Lebanon: 1M displaced, food insecurity)
  - Global commodity is in pressure surge (wheat: Black Sea grain corridor stress)
  - Country has structural import dependency on that commodity (Lebanon: 80% Black Sea wheat)
    → CONVERGENCE: humanitarian crisis × commodity surge × import dependency

This module is consumed by TWO layers of the analytical stack:

LAYER 2 — me_regional_bluf.py (and equivalents for other regions later):
  - Enriches existing humanitarian/stability signals with convergence context
  - Adds compound-risk language to the long_text of the trigger signal
  - Sets the {convergence_id}_active boolean flag on the signal for Layer 1 to read

LAYER 1 — global_pressure_index.py:
  - Detects convergence flags on signals flowing through regional BLUFs
  - Emits a NEW high-priority Tier-1 narrative for the convergence itself
  - Cross-regional tagging gives it +30 boost in synthesis ordering

ADDING A NEW CONVERGENCE:
  1. Append a dict to CONVERGENCE_REGISTRY below
  2. Verify the trigger_signal_category exists in the relevant regional BLUF
  3. Verify the commodity exists in commodity_tracker.COMMODITY_TYPES
  4. Deploy ME backend (both BLUF + GPI live there) — that's it

REQUIRED FIELDS per convergence entry:
  id                       — unique snake_case identifier (also used as category)
  commodity                — must match commodity_tracker COMMODITY_TYPES key
                             (use None for non-commodity-anchored convergences)
  country                  — primary country name for display + matching
  trigger_signal_category  — category string Layer 2 watches for in BLUF
  trigger_region           — which regional BLUF carries the trigger
                             (recognized: 'me', 'asia', 'europe', 'wha', 'africa')
  commodity_threshold      — min alert level: 'elevated', 'high', or 'surge'
  regions                  — list of regions for cross-regional Tier-1 boost
  priority                 — narrative priority (10-15 range)
  icon                     — emoji
  color                    — hex color
  headline_template        — supports {alert} placeholder for commodity status
  detail                   — static prose body
  facts                    — dict of structured anchors (display + audit)
  enrichment_text_template — Layer 2 long_text append (supports {alert}, {signals})

OPTIONAL FIELDS:
  trigger_signal_min_level — only fire if trigger signal is at this level or higher
  notes                    — analyst notes (not displayed)
"""

# ════════════════════════════════════════════════════════════════════
# THE REGISTRY
# ════════════════════════════════════════════════════════════════════

CONVERGENCE_REGISTRY = [
    {
        'id':                      'wheat_lebanon',
        'commodity':               'wheat',
        'country':                 'lebanon',
        'trigger_signal_category': 'humanitarian_lebanon',
        'trigger_region':          'me',
        'commodity_threshold':     'elevated',          # fires at elevated, high, or surge
        'regions':                 ['me', 'europe'],     # ME = Lebanon, Europe = Black Sea (UA/RU)
        'priority':                13,
        'icon':                    '\U0001f33e',         # 🌾
        'color':                   '#f59e0b',             # amber — economic axis primary
        'headline_template':       'Wheat-Lebanon convergence -- food security crisis compounded by global wheat {alert}',
        'detail': (
            'Lebanon imports ~60-67% of its wheat from Ukraine and ~80-90% combined '
            'from Black Sea (Ukraine + Russia). National wheat reserves stand at ~1 month '
            'since the 2020 Beirut port explosion destroyed national grain silos -- '
            'never rebuilt. 1.24M Lebanese projected to face acute food insecurity '
            '(IPC Phase 3+) through August 2026; Flash Appeal only 38% funded. '
            'Watch: Black Sea grain corridor status, Russian wheat export taxes, '
            'Lebanese Mills Association statements, Lebanese Pound bread-price index. '
            'Compound risk: any Black Sea disruption during active humanitarian crisis '
            'is materially worse than during peacetime.'
        ),
        'facts': {
            'import_dep_pct':  '60-67% Ukraine, 80-90% Black Sea',
            'reserve_months':  1,
            'reserve_note':    'silos destroyed in 2020 Beirut port explosion',
            'food_insecure':   '1.24M IPC Phase 3+ through Aug 2026',
            'appeal_funded':   '38%',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f WHEAT-LEBANON CONVERGENCE: Global wheat at {alert} '
            '({signals} signals). Lebanon imports ~60-67% of wheat from Ukraine and '
            '~80-90% combined Black Sea (UA+RU); national wheat reserves ~1 month '
            'since 2020 Beirut port explosion destroyed grain silos. Compound risk: '
            'any Black Sea grain corridor disruption is materially worse during active '
            'humanitarian crisis with 1.24M projected food-insecure (IPC Phase 3+).'
        ),
        'notes': (
            'Founding convergence -- shipped May 3, 2026. Lebanese wheat reserves '
            'have NOT been rebuilt since 2020 explosion; this is structural fragility.'
        ),
    },

    # ───────────────────────────────────────────────────────────────
    # ASIA CONVERGENCES (May 2026)
    # Cross-theater amplification narratives for the China-Taiwan-Japan
    # triangle, plus the China-Iran-Hormuz oil dependency vector.
    # Trigger region 'asia' or 'me' depending on origin signal.
    # ───────────────────────────────────────────────────────────────
    {
        'id':                      'pla_pressure_japan_response',
        'commodity':               None,                          # Not commodity-driven
        'country':                 'japan',
        'trigger_signal_category': 'japan_outbound_posture',
        'trigger_region':          'asia',
        'commodity_threshold':     None,                          # No commodity gate
        'regions':                 ['asia'],
        'priority':                14,
        'icon':                    '\U0001f396\ufe0f',             # 🎖️
        'color':                   '#ef4444',                       # red — security axis
        'headline_template':       'Asia security architecture activation -- China escalation + Japan posture hardening converge',
        'detail': (
            'Convergence pattern: China outbound rhetoric at L3+ (Directive or higher) '
            'AND Japan outbound posture at L3+ (PM/MoD/Diet committing to defense build-up '
            'or Article 9 reinterpretation language). When both fire simultaneously, '
            'this is the strongest available signal that East Asia security architecture '
            'is shifting from a bilateral US-Japan alliance frame to an explicit '
            'trilateral (US-Japan-Taiwan or US-Japan-Korea) posture. Watch for follow-on '
            'INDOPACOM signaling, Reciprocal Access Agreement updates, AUKUS Pillar 2 '
            'announcements, Japan-Philippines defense agreements. Compound risk: regional '
            'arms-race dynamics + reduced diplomatic off-ramp space.'
        ),
        'facts': {
            'china_threshold':    'outbound_max_level >= 3',
            'japan_threshold':    'outbound_max_level >= 3 OR article9_active',
            'historical_analog':  '2015 collective self-defense reinterpretation cycle',
            'key_indicators':     'JSDF deployment orders, INDOPACOM signaling, Diet votes',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f ASIA SECURITY ARCHITECTURE ACTIVATION: China outbound at {alert} '
            '({signals} signals) coincides with Japan posture hardening. This is the '
            'strongest convergence signal that regional alliance architecture is shifting '
            'toward explicit trilateral coordination. Watch INDOPACOM, RAA updates, AUKUS '
            'Pillar 2 expansion.'
        ),
        'notes': (
            'Asia-theatre founding convergence -- May 7 2026. Mirrors wheat-Lebanon '
            'pattern but for security rather than commodity axis.'
        ),
    },
    {
        'id':                      'taiwan_alliance_convergence',
        'commodity':               None,
        'country':                 'taiwan',
        'trigger_signal_category': 'taiwan_us_alliance',
        'trigger_region':          'asia',
        'commodity_threshold':     None,
        'regions':                 ['asia'],
        'priority':                14,
        'icon':                    '\U0001f91d',                    # 🤝
        'color':                   '#0ea5e9',                        # cyan — alliance axis
        'headline_template':       'Trilateral Taiwan defense convergence -- Japan + US + Taiwan signaling alignment',
        'detail': (
            'Convergence pattern: Japan taiwan_defense_active fingerprint TRUE + Taiwan '
            'us_alliance L3+ + (optionally) US INDOPACOM signaling at elevated levels. '
            'This converts what has historically been a strategically ambiguous '
            'US-Taiwan posture into an explicit trilateral defense commitment. '
            'Significantly raises the threshold for any PRC kinetic action against Taiwan '
            'and increases the probability of structured PLA escalation in response. '
            'Watch PLA Eastern Theater Command activity spikes, MFA condemnation cadence, '
            'TAO statements on "external interference."'
        ),
        'facts': {
            'japan_threshold':    'taiwan_defense_active = TRUE',
            'taiwan_threshold':   'us_alliance_level >= 3',
            'compound_effect':    'shift from strategic ambiguity to explicit trilateral commitment',
            'historical_analog':  '2021 Suga-Biden joint statement (Taiwan named for first time since 1969)',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f TRILATERAL TAIWAN DEFENSE CONVERGENCE: Japan committing to '
            'Taiwan defense + Taiwan signaling US alliance at {alert} ({signals} signals). '
            'Converts strategic ambiguity into explicit trilateral commitment. PLA '
            'escalation probability rises in response.'
        ),
        'notes': (
            'Captures the most consequential Asia convergence pattern -- '
            'Japan publicly defending Taiwan is a threshold change vs. all prior '
            'Japanese governments. Peter would have something to say about this.'
        ),
    },
    {
        'id':                      'hormuz_china_oil_dependency',
        'commodity':               'oil',
        'country':                 'china',
        'trigger_signal_category': 'iran_hormuz_pressure',
        'trigger_region':          'me',                            # Origin = Iran
        'commodity_threshold':     'elevated',                      # Lower bar than wheat-LBN
        'regions':                 ['me', 'asia'],                   # Cross-regional
        'priority':                15,                               # Highest -- structural China dependency
        'icon':                    '\U0001f6e2\ufe0f',                # 🛢️
        'color':                   '#f59e0b',                          # amber — economic axis
        'headline_template':       'China oil supply convergence -- Iran/Hormuz pressure compounded by China import dependency',
        'detail': (
            'China imports approximately 50% of its crude oil through the Strait of Hormuz. '
            'When Iran posture (theatre_score) reaches operational levels (L3+) or IRGC '
            'fingerprint shows Hormuz/Persian Gulf in named_targets, China faces direct '
            'pressure on its energy security. This explains why China consistently pushes '
            'de-escalation rhetoric in MFA briefings during Iran tensions, why China invests '
            'heavily in alternative supply (CPEC pipeline, BRI infrastructure, Russia-China '
            'oil pipelines, Central Asia gas), and why China has repeatedly mediated between '
            'Iran and Saudi Arabia. Compound risk: Hormuz disruption simultaneously with '
            'global oil pressure surge would force structural change to Chinese energy '
            'sourcing -- with cascading effects on Belt and Road, yuan settlement deals, '
            'and Sino-Iranian strategic partnership timelines.'
        ),
        'facts': {
            'china_oil_dep':       '~50% crude imports through Hormuz',
            'iran_threshold':      'theatre_score >= 60 OR irgc_level >= 3 OR hormuz in named_targets',
            'oil_threshold':       'elevated, high, or surge',
            'china_response':      'MFA de-escalation rhetoric, BRI/CPEC investment, RU/Central Asia substitution',
            'historical_analog':   '2019-2020 tanker-war period, 2024 Israel-Iran direct exchange',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f HORMUZ-CHINA OIL CONVERGENCE: Global oil at {alert} '
            '({signals} signals) AND Iran posture elevated. China imports ~50% of crude '
            'through Hormuz; Iran pressure on Hormuz directly stresses Chinese energy '
            'security. Watch China MFA "stability" framing, BRI/CPEC investment '
            'announcements, RU/Central Asia substitution moves, yuan settlement deal news.'
        ),
        'notes': (
            'First cross-regional Asia convergence (ME trigger -> Asia consumer). '
            'Mirrors wheat-Lebanon pattern (ME-trigger -> Europe-consumer). '
            'This is THE structural reason China cares so much about Iran. '
            'May 7 2026 -- Rachel + Peter contribution.'
        ),
    },

    # ───────────────────────────────────────────────────────────────
    # REGIME SIGNALS (May 7 2026)
    # A third axis distinct from commodity (wheat/oil) and security (PLA/Taiwan).
    # Regime signals measure STRUCTURAL SHIFTS in the international system itself:
    # the post-1971 dollar order, the post-1945 sanctions architecture, the
    # post-Cold-War arms trade flows, the post-1973 OPEC oil order. These are
    # higher-order patterns — convergences of convergences — that emerge when
    # multiple states behave in ways consistent with a coordinated alternative
    # to the existing system.
    #
    # IMPORTANT: These are MEASUREMENT signals, not assertions. Asifah does not
    # claim "the system is fragmenting." It measures how many indicators
    # consistent with that thesis are firing, and lets the analyst decide.
    #
    # PHASE STATUS (as of May 7 2026):
    #   Phase 1 ✅ — Registry entries (this file)
    #   Phase 2 ⏳ — Tracker keyword bundles + fingerprint fields
    #   Phase 3 ⏳ — Country rhetoric cards, regional BLUF prose, GPI surfacing
    # ───────────────────────────────────────────────────────────────
    {
        'id':                      'financial_system_fragmentation',
        'commodity':               None,                            # Regime-axis, not commodity
        'country':                 'iran',                          # Iran is densest near-term signal source
        'trigger_signal_category': 'iran_dedollarization_active',   # Wired in Phase 2 (Iran tracker)
        'trigger_region':          'me',
        'commodity_threshold':     None,
        'regions':                 ['me', 'asia', 'europe'],         # Genuinely global
        'priority':                18,                                # Top of pyramid — regime-level > commodity-level
        'icon':                    '\U0001f310',                      # 🌐
        'color':                   '#a855f7',                          # purple — regime axis (distinct from amber/red/cyan)
        'headline_template':       'Financial system fragmentation -- parallel infrastructure construction across sanctioned states',
        'detail': (
            'STRUCTURAL READOUT: When sanctioned and aligned states (Iran, Russia, '
            'China, Belarus, DPRK) simultaneously build out non-dollar payment '
            'infrastructure -- gold-for-oil settlement, yuan-denominated trade, CIPS '
            'integration, BRICS Pay, mBridge CBDC, SPFS, gold reserve accumulation -- '
            'this is no longer tactical sanctions evasion. It is parallel infrastructure '
            'construction. The post-Bretton Woods dollar-denominated international '
            'financial order is being actively bypassed at sufficient scale to constitute '
            'a measurable structural shift. WHAT IT MEANS: the dollar system\'s network '
            'effects (deep capital markets, SWIFT messaging, correspondent banking) '
            'remain dominant in volume terms -- but the existence of a functioning '
            'parallel system means the U.S. financial sanctions toolkit is materially '
            'less effective against coordinated bloc actors than it was in the '
            '2012-2018 period. Watch: percent of Russia-China trade settled in non-USD; '
            'CIPS daily transaction volumes; Iran gold market activity (Tehran gold '
            'bourse SURGE -- already firing per dashboard 5/7/2026); BRICS Pay rollout '
            'milestones; central bank gold reserve buying (especially PBOC). Compound '
            'risk: each new participating country lowers the marginal cost for the next '
            'one to join (network effect).'
        ),
        'facts': {
            'system_at_risk':     'post-Bretton Woods dollar-denominated trade settlement',
            'parallel_systems':   'CIPS (China), SPFS (Russia), BRICS Pay, mBridge CBDC, gold-for-oil',
            'dollar_share':       '~88% of FX transactions (BIS) — still dominant, but trending',
            'historical_analog':  '1971 Nixon shock (regime change, not crisis)',
            'inflection_signal':  'gold-for-oil settlement at sustained commercial scale',
            'firing_today':       'Iran gold market SURGE (sanctions evasion) — L4 economic — 5/7/2026',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f FINANCIAL SYSTEM FRAGMENTATION: {signals} regime indicators '
            'firing at {alert} levels across sanctioned/aligned states. Gold-for-oil '
            'settlement, yuan-denominated trade, CIPS integration, BRICS Pay, gold '
            'reserve accumulation -- parallel financial infrastructure construction at '
            'scale. STRUCTURAL READ: post-Bretton Woods dollar-settlement order '
            'increasingly bypassable by coordinated bloc actors. U.S. sanctions toolkit '
            'effectiveness materially degraded vs 2012-2018 baseline. Watch CIPS volumes, '
            'central bank gold buying, Russia-China non-USD trade share.'
        ),
        'notes': (
            'TOP-OF-PYRAMID regime signal -- May 7 2026. The most consequential '
            'measurement Asifah produces. Inspired by 5/7 dashboard catching Iran '
            'gold market SURGE (L4 economic) -- ChatGPT correctly identified the '
            'meta-pattern but could not measure it. Asifah can. PHASE 2 NEEDS: '
            'iran_dedollarization_active fingerprint in Iran tracker '
            '(gold-for-oil keywords, Bourse, Sepah Bank, yuan settlement). '
            'PHASE 3 NEEDS: surfacing on Iran/China/Russia rhetoric pages, ME+Asia+Europe '
            'BLUFs, top of GPI. Honest framing: this measures the thesis, does not '
            'assert it. Diplomats and policymakers can decide if 7-of-12 indicators '
            'firing constitutes regime change.'
        ),
    },
    {
        'id':                      'dedollarization_drumbeat',
        'commodity':               None,
        'country':                 'china',                          # China MFA is densest rhetoric source
        'trigger_signal_category': 'china_yuan_internationalization',
        'trigger_region':          'asia',
        'commodity_threshold':     None,
        'regions':                 ['asia', 'me', 'europe'],          # Cross-bloc rhetoric
        'priority':                17,                                  # Just below fragmentation -- rhetoric < action
        'icon':                    '\U0001f4e2',                         # 📢
        'color':                   '#a855f7',                            # purple — regime axis
        'headline_template':       'Dedollarization drumbeat -- coordinated public commitment to alternative settlement',
        'detail': (
            'STRUCTURAL READOUT: Public-stage rhetoric from senior officials of major '
            'states (China MFA, Russia MFA, Iranian leadership, Brazilian/Indian '
            'finance ministry, ASEAN bodies) explicitly naming dedollarization, '
            'SWIFT alternatives, BRICS settlement, or yuan internationalization as '
            'policy goals. WHAT IT MEANS: rhetoric is downstream of action -- but it '
            'is also a forward indicator. When officials publicly commit to a regime '
            'alternative, they are (a) accepting domestic political cost of the framing, '
            '(b) signaling to other states that coordination is welcome, and (c) raising '
            'the cost of policy reversal. This is distinct from financial_system_'
            'fragmentation, which measures behavior; this measures public commitment. '
            'Both can fire independently. Watch: BRICS summit communiques, China MFA '
            'press briefings on financial sovereignty, Lavrov/Putin SPIEF speeches, '
            'Iranian leadership Friday sermons on resistance economy, Lula/Modi joint '
            'statements on multipolar trade. Compound risk: rhetoric coordination '
            'precedes operational coordination by 6-18 months historically.'
        ),
        'facts': {
            'measurement':        'public-stage commitment to non-dollar settlement',
            'distinguishing':     'measures rhetoric, not behavior (vs fragmentation)',
            'lead_indicator':     '6-18 month forward signal for operational coordination',
            'historical_analog':  '2009-2014 BRICS bank rhetoric -> 2015 NDB launch',
            'key_speakers':       'China MFA, Russia MFA, Iran leadership, Lula, Modi, Putin SPIEF',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f DEDOLLARIZATION DRUMBEAT: {signals} senior-official statements '
            'at {alert} levels naming dedollarization/SWIFT-alternatives/BRICS-settlement '
            'as policy goals. PUBLIC COMMITMENT signal -- distinct from behavioral '
            'fragmentation. Historically a 6-18 month lead indicator for operational '
            'coordination. Watch BRICS summits, MFA briefings, SPIEF speeches.'
        ),
        'notes': (
            'Rhetoric-driven companion to financial_system_fragmentation. Both can '
            'fire independently. PHASE 2 NEEDS: china_yuan_internationalization '
            'category in China tracker (CIPS, BRICS Pay, mBridge keywords); also adds '
            'similar fingerprints to Russia (Lavrov/Putin) and Iran (resistance economy) '
            'trackers. PHASE 3 NEEDS: surfacing on rhetoric pages + regional BLUFs + GPI.'
        ),
    },
    {
        'id':                      'sanctions_evasion_cluster',
        'commodity':               None,
        'country':                 'iran',                          # Iran is densest evasion source
        'trigger_signal_category': 'iran_gold_for_oil_active',      # FIRING TODAY -- L4 economic
        'trigger_region':          'me',
        'commodity_threshold':     None,
        'regions':                 ['me', 'europe', 'asia'],          # Iran/Russia/Belarus + China facilitation
        'priority':                16,
        'icon':                    '\U0001f4b0',                      # 💰
        'color':                   '#a855f7',                          # purple — regime axis
        'headline_template':       'Sanctions evasion cluster -- coordinated tactical bypass across multiple sanctioned states',
        'detail': (
            'STRUCTURAL READOUT: Tactical-level sanctions evasion behavior firing '
            'simultaneously across multiple sanctioned states (Iran, Russia, Belarus, '
            'DPRK) -- gold-for-oil settlement, shadow fleet operations, third-country '
            'reflagging, sanctioned-bank renaming, named-individual evasion entities, '
            'crypto/stablecoin trade settlement. WHAT IT MEANS: when evasion behavior '
            'clusters in time across uncoordinated regimes, it suggests either '
            '(a) shared methodology transfer (sanctioned states learning from each '
            'other), (b) shared facilitator networks (likely Chinese SOE banks, Turkish '
            'gold dealers, UAE/Hong Kong/Singapore intermediaries), or (c) coordinated '
            'response to specific Western sanctions actions. This is NOT regime change '
            'on its own -- evasion has existed since sanctions existed. The signal is '
            'INTENSITY: when 3+ sanctioned states show simultaneous high-evasion '
            'activity, the U.S. sanctions enforcement bandwidth is materially '
            'overstretched. Watch: Iran gold market activity (FIRING TODAY 5/7/2026), '
            'Russian shadow fleet incidents, OFAC SDN list additions, Treasury 311 '
            'special measures, sanctioned-bank renaming patterns.'
        ),
        'facts': {
            'firing_today':        'Iran gold market SURGE (L4 economic) -- 5/7/2026',
            'measurement':         'simultaneous evasion intensity across 3+ sanctioned states',
            'distinguishing':      'tactical bypass (vs structural fragmentation)',
            'key_facilitators':    'Chinese SOE banks, Turkish gold dealers, UAE/HK/SG intermediaries',
            'us_implication':      'OFAC enforcement bandwidth overstretch when 3+ states fire simultaneously',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f SANCTIONS EVASION CLUSTER: {signals} evasion indicators at '
            '{alert} levels across Iran/Russia/Belarus/DPRK -- gold-for-oil, shadow '
            'fleet, third-country reflagging, sanctioned-bank renaming. STRUCTURAL READ: '
            'tactical bypass intensity, not regime change -- but when 3+ states fire '
            'simultaneously, OFAC enforcement bandwidth is overstretched. Watch Iran '
            'gold market, Russian shadow fleet, Treasury 311 actions.'
        ),
        'notes': (
            'Tactical-level companion to financial_system_fragmentation -- evasion '
            'happens at all times; the signal is intensity and simultaneity. '
            'Iran gold market SURGE (5/7/2026) is the trigger that prompted this entire '
            'regime-signal architecture. PHASE 2 NEEDS: iran_gold_for_oil_active '
            'fingerprint (Tehran Bourse, Sepah Bank, gold-for-oil keywords); '
            'russia_shadow_fleet_active in Russia tracker; belarus_sanctions_relay in '
            'Belarus tracker. PHASE 3 NEEDS: surfacing.'
        ),
    },
    {
        'id':                      'arms_trade_realignment',
        'commodity':               None,
        'country':                 'russia',                        # Russia is biggest non-Western arms exporter
        'trigger_signal_category': 'russia_arms_export_active',
        'trigger_region':          'europe',
        'commodity_threshold':     None,
        'regions':                 ['europe', 'me', 'asia'],          # Russia <-> Iran/DPRK/Venezuela/China
        'priority':                16,
        'icon':                    '\U0001f6e9\ufe0f',                # 🛩️
        'color':                   '#a855f7',                          # purple — regime axis
        'headline_template':       'Arms trade realignment -- weapons flows along non-Western channels',
        'detail': (
            'STRUCTURAL READOUT: Major weapons transfers flowing along Russia-Iran-DPRK-'
            'Venezuela-China channels rather than U.S./NATO/Israeli/European supply '
            'chains. Specifically: Iranian Shahed drones to Russia, North Korean '
            'artillery shells to Russia, Russian Su-35s/S-400s to Iran, Chinese drone '
            'components to Iran/Russia, Russian air defense to Venezuela. WHAT IT MEANS: '
            'the post-Cold-War arms trade order assumed Western (especially U.S.) '
            'dominance in advanced systems and quasi-monopoly on supplier-of-choice '
            'status for non-aligned states. When sanctioned states begin acting as '
            'major weapons suppliers TO each other AND to non-aligned third parties, '
            'this represents structural change -- a parallel arms trade ecosystem with '
            'its own training pipelines, maintenance contracts, and doctrinal exchange. '
            'Compound effect: each successful transfer establishes precedent that '
            'lowers political cost of the next. Watch: SIPRI annual data, named-system '
            'transfers in Telegram OSINT (Shahed sightings, S-400 deployments), '
            'Treasury sanctions on supplier networks, third-country end-user '
            'destinations (Algeria, Vietnam, Egypt purchase decisions).'
        ),
        'facts': {
            'measurement':        'weapons flows along Russia-Iran-DPRK-Venezuela-China axes',
            'systems_in_play':    'Shahed drones, NK artillery, S-400, Su-35, Chinese drone components',
            'historical_analog':  'Cold War parallel arms trade (Soviet bloc) -- though current is more transactional',
            'doctrine_signal':    'training pipelines, maintenance contracts, doctrinal exchange',
            'key_data_sources':   'SIPRI annual, Telegram OSINT named-system sightings, Treasury sanctions',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f ARMS TRADE REALIGNMENT: {signals} weapons-transfer indicators '
            'at {alert} levels along Russia-Iran-DPRK-Venezuela-China channels. '
            'STRUCTURAL READ: parallel arms trade ecosystem with own training/maintenance/'
            'doctrine pipelines. Each transfer lowers political cost of next. Watch '
            'SIPRI data, Shahed sightings, third-country end-user decisions.'
        ),
        'notes': (
            'Military-axis companion to financial regime signals. Russia-DPRK shell '
            'transfers + Iran-Russia Shahed transfers are the headline patterns of '
            '2024-2026. PHASE 2 NEEDS: russia_arms_export_active in Russia tracker; '
            'similar fingerprint additions in Iran (Shahed exports), DPRK (when DPRK '
            'tracker exists), Venezuela (when WHA expands). PHASE 3 NEEDS: surfacing on '
            'Russia/Iran rhetoric pages, Europe + ME BLUFs, GPI.'
        ),
    },
    {
        'id':                      'energy_bloc_consolidation',
        'commodity':               None,                            # Meta-signal across oil/gas
        'country':                 'iran',                          # Iran is densest near-term trigger
        'trigger_signal_category': 'iran_opec_realignment',
        'trigger_region':          'me',
        'commodity_threshold':     None,
        'regions':                 ['me', 'europe', 'asia'],          # OPEC-Russia-China energy axis
        'priority':                16,
        'icon':                    '\u26fd',                          # ⛽
        'color':                   '#a855f7',                          # purple — regime axis
        'headline_template':       'Energy bloc consolidation -- OPEC+ fragmentation and sanctioned-state oil flows',
        'detail': (
            'STRUCTURAL READOUT: The post-1973 OPEC oil order is showing measurable '
            'stress -- UAE leaving OPEC+ effective May 1 2026 (first major departure '
            'since Qatar 2019, stated cause: GCC failure to defend UAE during Iran war), '
            'Iranian oil flowing to China outside OPEC quota framework, Russian oil '
            'flowing to India/China at G7 price-cap-violating prices via shadow fleet, '
            'Saudi-Iran rapprochement reducing Saudi-aligned-with-West reflexive '
            'positioning. WHAT IT MEANS: the Western assumption of OPEC discipline as '
            'a price-management mechanism (independent of Western policy) is eroding. '
            'When sanctioned states (Iran, Russia, Venezuela) sell oil at scale outside '
            'the OPEC framework, AND when major OPEC members (UAE, potentially Saudi) '
            'distance themselves from OPEC discipline, the result is a more '
            'fragmented energy market with reduced Western policy leverage. Compound '
            'risk: combined with financial_system_fragmentation, you get sanctioned-'
            'state oil settling in non-USD currency at non-OPEC pricing -- a parallel '
            'energy economy. Watch: OPEC+ quota compliance reports, UAE production '
            'announcements, Saudi-Iran joint statements, Russian/Iranian oil shipment '
            'data, India/China refinery sourcing decisions.'
        ),
        'facts': {
            'firing_today':       'UAE leaving OPEC+ effective 5/1/2026 (Mamdouh Salameh statement)',
            'measurement':        'OPEC+ discipline + sanctioned-state oil flows + non-USD oil settlement',
            'historical_analog':  '1970s OPEC formation in reverse -- post-OPEC fragmentation',
            'compound_signal':    'energy_bloc + financial_fragmentation = parallel energy economy',
            'key_data_sources':   'OPEC monthly reports, UAE/Saudi production data, shadow fleet OSINT',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f ENERGY BLOC CONSOLIDATION: {signals} OPEC-fragmentation/'
            'sanctioned-flow indicators at {alert} levels. UAE departure (5/1/2026), '
            'Iran-China non-OPEC oil flows, Russia-India shadow fleet pricing. '
            'STRUCTURAL READ: post-1973 OPEC discipline eroding; combined with financial '
            'fragmentation = parallel energy economy. Watch OPEC compliance, UAE/Saudi '
            'production, India/China refinery sourcing.'
        ),
        'notes': (
            'Energy-axis companion to financial regime signals. Trigger today: UAE '
            'leaving OPEC+ (4/28 strategic signal in memory). PHASE 2 NEEDS: '
            'iran_opec_realignment fingerprint in Iran tracker; uae_opec_departure '
            'fingerprint when UAE tracker exists. Saudi-Iran rapprochement signal '
            'should also feed this. PHASE 3 NEEDS: surfacing on Iran/Saudi/UAE pages, '
            'ME BLUF, GPI. Connects to memory-noted UAE OPEC departure 4/28/2026.'
        ),
    },


    # ───────────────────────────────────────────────────────────────
    # AFRICA / BELT-AND-ROAD / SANCTIONS CONVERGENCES (May 23 2026)
    # Phase 1A Africa launch + diamonds sanctions architecture.
    # These four convergences capture the structural pattern of
    # critical-minerals great-power competition: resource-leverage,
    # sanctions enforcement, and food-security cascades anchored in
    # African + Jordanian commodity producers.
    # ───────────────────────────────────────────────────────────────
    {
        'id':                      'cobalt_drc_active',
        'commodity':               'cobalt',
        'country':                 'drc',
        'trigger_signal_category': 'drc_conflict_kivu',
        'trigger_region':          'africa',                       # Theatre = Africa (when africa.html ships)
        'commodity_threshold':     'elevated',
        'regions':                 ['africa', 'asia', 'wha'],     # DRC = producer, China = consumer, US = strategic re-entry
        'priority':                15,                              # Highest -- structural EV-battery dependency
        'icon':                    '\U0001f50b',                   # 🔋
        'color':                   '#f59e0b',                       # amber — economic axis
        'headline_template':       'DRC cobalt supply convergence -- Kivu instability compounded by global cobalt {alert}',
        'detail': (
            'DRC produces ~72% of global cobalt supply (essential for EV battery NMC '
            'cathode chemistry). CCP-linked entities control ~80% of Congolese cobalt '
            'mining (15 of 19 best deposits per public reporting); China refines ~73% '
            'of global cobalt regardless of mine origin. STRUCTURAL REPOSITIONING (2025-2026): '
            'US-DRC Strategic Partnership signed 2025; Orion Critical Mineral Consortium '
            'MOU with Glencore (Feb 2026) signals Western re-entry; Project Vault channels '
            'DRC minerals into US strategic stockpiles; June 2025 US-brokered DRC-Rwanda '
            'peace deal explicitly tied to mineral access. EASTERN CONGO CONFLICT: M23 + '
            'ADF + FDLR + Russia-linked PMC (Africa Corps) operations create real-time '
            'supply disruption risk + sanctions-evasion gold-flow architecture. Compound risk: '
            'any DRC instability (Kivu surge, Kinshasa political crisis, Lobito Corridor '
            'disruption) during global cobalt price pressure forces structural change to '
            'Chinese + Western battery supply chains. Watch: M23 territorial control, '
            'Lobito throughput, Glencore-Orion offtake terms, Kinshasa-Beijing renegotiation.'
        ),
        'facts': {
            'drc_cobalt_share':    '~72% of global mined cobalt',
            'china_refining':      '~73% of global cobalt refining',
            'china_drc_control':   '~80% of DRC cobalt mining via CCP-linked entities',
            'us_repositioning':    'US-DRC Strategic Partnership (2025) + Orion MOU (Feb 2026) + Project Vault',
            'lobito_corridor':     'DRC->Zambia->Angola rail bypasses Chinese-controlled infrastructure',
            'historical_analog':   'No clean analog -- this is the canonical critical-minerals great-power competition test case',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f COBALT-DRC CONVERGENCE: Global cobalt at {alert} '
            '({signals} signals) AND DRC instability elevated. DRC produces ~72% of global '
            'cobalt; CCP-linked entities control ~80% of mining. US-DRC Strategic Partnership '
            '(2025) + Orion MOU (Feb 2026) + Project Vault repositioning Western access. '
            'Compound risk: Kivu instability + global cobalt pressure stresses BOTH Chinese '
            'and Western EV battery supply chains. Watch M23 territorial control, Lobito '
            'throughput, Glencore-Orion offtake terms.'
        ),
        'notes': (
            'Africa Phase 1A convergence -- May 23 2026 build. Activates the placeholder '
            'cobalt_drc that has lived in this registry since v1.0. trigger_region=africa '
            'will need africa_regional_bluf.py to emit drc_conflict_kivu category once '
            'rhetoric_tracker_sudan.py and africa.html ship. Until then, can be triggered '
            'manually via /api/convergence/cobalt_drc_active or read by GPI directly.'
        ),
    },
    {
        'id':                      'diamonds_sanctions_regime',
        'commodity':               'diamonds',
        'country':                 'botswana',                      # Anchor = G7 cert node host
        'trigger_signal_category': 'g7_diamond_enforcement_stress',
        'trigger_region':          'africa',                        # Trigger region = Africa producers
        'commodity_threshold':     'elevated',
        'regions':                 ['africa', 'europe', 'asia', 'me'],  # Africa=producers, EU=Antwerp, Asia=India/HK, ME=UAE
        'priority':                15,                               # Specialized but architecturally important
        'icon':                    '\U0001f48e',                    # 💎
        'color':                   '#a855f7',                          # purple — regime axis (sanctions-enforcement)
        'headline_template':       'Diamond sanctions regime convergence -- G7 enforcement architecture under stress',
        'detail': (
            'STRUCTURAL READOUT: The G7 sanctions regime on Russian diamonds (effective '
            'Jan 1 2024 direct ban + March 1 2024 third-country ban) routes ALL '
            'compliance enforcement through two certification nodes: Antwerp (Belgium, '
            'operational since March 1 2024) and Botswana (under construction with G7 '
            'technical team since Nov 27 2024). When 2+ of the following fire '
            'simultaneously, the enforcement architecture is materially stressed: '
            '(1) Russian-origin seizures at Antwerp/EU customs spike, (2) Botswana cert '
            'node operational delays or political pressure, (3) Russian rough re-routing '
            'volume through UAE (DMCC) + India (Surat cutters) rises sharply, '
            '(4) De Beers ownership-event volatility (Anglo American $4.9B divestment + '
            'Botswana-Angola joint-acquisition talks), (5) lab-grown diamond market share '
            'displacement accelerates beyond 50% of US engagement-ring market. WHAT IT '
            'MEANS: diamonds are uniquely fungible + high-value-per-gram + opaque -- '
            'making them the canonical sanctions-evasion substrate for high-net-worth '
            'Russian flows. When the G7 architecture stresses, the broader sanctions '
            'regime credibility comes under pressure. Watch: Belgian Federal Police '
            'seizure announcements, DMCC monthly trade volumes, GJEPC Russian-rough '
            'boycott compliance, Botswana credit rating actions.'
        ),
        'facts': {
            'g7_ban_effective':    'Direct Russian ban Jan 1 2024; third-country ban Mar 1 2024',
            'cert_nodes':          'Antwerp (Belgium) operational; Botswana under construction',
            'russian_pre_ban':     'Alrosa was world #2-3 rough exporter at ~$3.8B/yr by value',
            'evasion_routes':      'UAE (DMCC) + India (Surat cutters) + Hong Kong mixed-origin polishing',
            'belgian_seizures':    'Belgian customs seized millions in suspected Russian-origin stones Feb 2024',
            'de_beers_event':      'Anglo American $4.9B divestment + Botswana-Angola joint-acquisition talks (May 2025)',
            'botswana_fiscal_exp': 'Diamonds = ~75% Botswana exports, ~30% GDP',
            'lab_grown_pressure':  '~50% of US engagement-ring market is now synthetic',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f DIAMOND SANCTIONS REGIME: {signals} G7-enforcement-stress '
            'indicators at {alert} levels across Antwerp + Botswana cert nodes, UAE/India '
            'evasion routes, De Beers ownership events. STRUCTURAL READ: G7 Russian-diamond '
            'ban enforcement architecture under stress; diamonds are canonical sanctions-'
            'evasion substrate for Russian flows. Watch Belgian seizure announcements, '
            'DMCC trade volumes, GJEPC Russian-rough boycott compliance, Botswana cert '
            'node readiness.'
        ),
        'notes': (
            'Africa Phase 1A convergence -- May 23 2026 build. Dedicated sanctions-regime '
            'hook for diamonds per Coco preference (Option B, deeper build). '
            'PHASE 2 NEEDS: g7_diamond_enforcement_stress fingerprint emitter -- likely '
            'lives in europe_regional_bluf.py (Antwerp/AWDC scanning) + africa_regional_bluf.py '
            '(Botswana cert-node tracking when shipped) + me_regional_bluf.py (UAE DMCC '
            'mediator scanning). PHASE 3 NEEDS: surfacing on rhetoric-russia.html + '
            'belgium country page (when shipped) + africa.html + GPI narrative. Companion '
            'to sanctions_evasion_cluster -- specialized rather than general; could merge '
            'later if Phase 2 build shows overlap.'
        ),
    },
    {
        'id':                      'belt_and_road_resource_leverage',
        'commodity':               None,                             # Meta-signal across cobalt/bauxite/potash/etc
        'country':                 'china',                          # Anchor = the resource-leverager
        'trigger_signal_category': 'china_resource_leverage_active',
        'trigger_region':          'asia',                           # Trigger from China-side rhetoric
        'commodity_threshold':     None,
        'regions':                 ['asia', 'africa', 'me'],         # China = leverager, Africa+ME = anchors
        'priority':                16,                               # Highest -- structural BRI architecture
        'icon':                    '\U0001f3ed',                     # 🏭
        'color':                   '#a855f7',                          # purple — regime axis
        'headline_template':       'Belt and Road resource-leverage convergence -- coordinated Chinese stakes in critical-commodity producers',
        'detail': (
            'STRUCTURAL READOUT: The Belt-and-Road Initiative includes a recurring '
            'resource-leverage architecture in which Chinese state capital acquires '
            'controlling or significant equity stakes in developing-country flagship '
            'resource companies, in exchange for infrastructure investment (rail, port, '
            'power). When 3+ of these anchor relationships fire simultaneously with '
            'visible rhetoric/policy stress, the pattern indicates either coordinated '
            'Chinese strategic positioning OR coordinated host-country renegotiation '
            'pressure. CANONICAL ANCHORS (current registry): (1) China-DRC cobalt -- '
            '~80% of Congolese mining via CCP-linked entities; (2) China-Guinea bauxite -- '
            'SMB Winning + Boké railway + Conakry port; (3) China-Jordan potash -- '
            'SDIC owns 28% of Arab Potash Company since 2017 ($500M); (4) China-Indonesia '
            'nickel -- Tsingshan + Huayou + GEM Co dominate Sulawesi HPAL parks; '
            '(5) China-Angola/Zambia/Mozambique infrastructure-for-resources packages. '
            'WHAT IT MEANS: when multiple anchor relationships simultaneously show stress '
            '(Western re-entry deals, host-country export quotas, leadership transitions, '
            'sovereign renegotiation rhetoric), the BRI resource architecture itself is '
            'under pressure -- not just any single commodity. Watch: Arab-Chinese '
            'Cooperation Forum outcomes (June 2026), DRC-Beijing renegotiation signals, '
            'Guinea SMB output disruptions, Indonesian nickel export-policy shifts, '
            'SDIC Jordan presence, Lobito Corridor throughput as Western counter-positioning.'
        ),
        'facts': {
            'anchor_pattern':       'Chinese state capital + flagship resource company stake + infrastructure investment',
            'current_anchors':      'DRC cobalt, Guinea bauxite, Jordan potash, Indonesia nickel, multiple Sub-Saharan infrastructure-for-resources',
            'sdic_jordan':          '28% of Arab Potash Co since 2017 ($500M)',
            'china_drc':            '~80% of DRC cobalt mining via CCP-linked entities',
            'china_guinea':         'SMB Winning + Boké-Conakry rail + Kamsar/Conakry ports',
            'china_indonesia':      'Tsingshan + Huayou + GEM Co Sulawesi HPAL parks',
            'western_counter':      'Lobito Corridor (US DFC + EU + G7 $2.5B 2023-2026)',
            'measurement':          '3+ anchor relationships under simultaneous renegotiation/replacement pressure',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f BELT-AND-ROAD RESOURCE LEVERAGE: {signals} indicators at '
            '{alert} levels across China-anchored resource relationships (DRC cobalt, '
            'Guinea bauxite, Jordan potash, Indonesia nickel). STRUCTURAL READ: BRI '
            'resource architecture under pressure; multiple host countries simultaneously '
            'renegotiating Chinese stakes or accepting Western counter-positioning '
            '(Lobito, Project Vault, Orion MOU). Watch Arab-Chinese Cooperation Forum '
            'outcomes, DRC-Beijing renegotiation, Indonesian nickel policy shifts.'
        ),
        'notes': (
            'Africa Phase 1A convergence -- May 23 2026 build. Meta-convergence linking '
            'multiple commodity-specific stories (cobalt_drc_active, bauxite_guinea '
            '[future], potash_jordan [future], nickel_indonesia [future]) into one '
            'structural pattern. Companion to financial_system_fragmentation -- BRI '
            'resource leverage is the COMMERCIAL/INFRASTRUCTURE axis of the same '
            'multi-axis structural-realignment story. PHASE 2 NEEDS: china_resource_leverage_active '
            'fingerprint emitter in china rhetoric tracker + per-country anchor '
            'fingerprints (drc_belt_and_road_active, guinea_belt_and_road_active, '
            'jordan_belt_and_road_active, indonesia_belt_and_road_active). PHASE 3 '
            'NEEDS: surfacing on GPI as Tier-1 narrative when 3+ anchor fingerprints '
            'fire simultaneously.'
        ),
    },
    {
        'id':                      'phosphate_food_security',
        'commodity':               'phosphate',
        'country':                 'morocco',                       # Anchor = OCP, world #1 phosphate
        'trigger_signal_category': 'phosphate_supply_stress',
        'trigger_region':          'africa',                        # Trigger from Morocco/OCP signal
        'commodity_threshold':     'elevated',
        'regions':                 ['africa', 'asia', 'me'],         # Africa=producers, Asia=India consumer, ME=Jordan+Saudi+Hormuz cascade
        'priority':                14,                               # High -- food-security cascade
        'icon':                    '\U0001fab5',                     # 🪵 placeholder for phosphate rock 🪨
        'color':                   '#f59e0b',                          # amber — economic axis
        'headline_template':       'Phosphate supply convergence -- Moroccan-OCP {alert} compounded by India import dependency + Hormuz sulfur cascade',
        'detail': (
            'Morocco/OCP controls ~70% of global proven phosphate reserves -- the most '
            'geographically concentrated fertilizer input on Earth. India is the world #1 '
            'phosphate consumer (~10-12 Mt/yr DAP/MAP) and ~90% reliant on imports -- '
            'single most concentrated fertilizer dependency on Earth. CASCADE LINK: '
            'phosphate processing into DAP/MAP fertilizers requires sulfuric acid, which '
            'flows downstream from the Hormuz Sulfur Cascade -- meaning any Hormuz '
            'disruption + China sulfur export ban directly elevates Indian + Brazilian + '
            'Egyptian DAP/MAP prices. WHAT IT MEANS: when (1) Moroccan OCP guidance '
            'tightens (export quotas, EU-Western Sahara legal challenges, OCP financial '
            'stress), (2) Indian phosphate tender stress (IPL/Coromandel/IFFCO failed '
            'tenders or extreme price-take), and (3) Hormuz sulfur cascade active -- '
            'global agricultural input prices spike, with downstream effects on Egyptian + '
            'Indian + Brazilian + Sub-Saharan-African food security. Compound risk: '
            'phosphate stress during active humanitarian crisis (Lebanon, Yemen, Sudan, '
            'eastern DRC) is materially worse. Watch: OCP quarterly results, India DAP '
            'tender outcomes (IPL/Coromandel), Hormuz sulfur cascade status (cascade_detector), '
            'Brazil DAP import volumes, Egyptian Mostakbal Misr fertilizer purchasing.'
        ),
        'facts': {
            'morocco_share':       '~70% of global proven phosphate reserves (OCP Group)',
            'india_dep':           'World #1 phosphate consumer, ~90% imported',
            'cascade_link':        'Phosphate -> DAP/MAP requires sulfuric acid (Hormuz cascade)',
            'historical_analog':   '2008 fertilizer crisis (DAP +400% YoY) catalyzed food riots in 30+ countries',
            'western_sahara':      'EU court rulings (2024) distinguish Bou Craa provenance from Morocco-proper',
            'food_security_chain': 'Morocco OCP -> India/Brazil/Egypt DAP -> grain yields -> food prices -> stability',
        },
        'enrichment_text_template': (
            '\u26a0\ufe0f PHOSPHATE-FOOD-SECURITY CONVERGENCE: Global phosphate at {alert} '
            '({signals} signals). Morocco/OCP controls ~70% of global reserves; India is '
            '~90% import-dependent at world #1 consumption levels. Hormuz sulfur cascade '
            'flows downstream into DAP/MAP prices. Compound risk: phosphate stress during '
            'active humanitarian crises (Lebanon, Yemen, Sudan) materially worsens food '
            'security. Watch OCP guidance, India DAP tenders, Hormuz sulfur cascade status.'
        ),
        'notes': (
            'Africa Phase 1A convergence -- May 23 2026 build. Fourth axis of food-security '
            'architecture alongside wheat_lebanon (existing). Phosphate is the agri-supply '
            'story that potash + sulfur + commodity tracker collectively expose but no '
            'single convergence has captured. PHASE 2 NEEDS: phosphate_supply_stress '
            'fingerprint emitter -- could live in cascade_detector.py as 4th cascade '
            'chain (hormuz_phosphate_cascade) OR as standalone fingerprint in morocco '
            'commodity exposure scanning. PHASE 3 NEEDS: surfacing on morocco country '
            'page (when shipped) + india-stability.html + GPI economic-axis narrative.'
        ),
    },

    # ───────────────────────────────────────────────────────────────
    # FUTURE CONVERGENCES — uncomment / adapt as new ones get identified.
    # Examples sketched below show how broad the pattern can stretch.
    # ───────────────────────────────────────────────────────────────
    # {
    #     'id':                      'wheat_egypt',
    #     'commodity':               'wheat',
    #     'country':                 'egypt',
    #     'trigger_signal_category': 'humanitarian_egypt',     # would need to exist
    #     'trigger_region':          'me',                       # or 'africa' if Egypt routed there
    #     'commodity_threshold':     'high',                     # higher bar for Egypt (more reserves)
    #     'regions':                 ['me', 'europe'],
    #     'priority':                12,
    #     'icon':                    '\U0001f33e',
    #     'color':                   '#f59e0b',
    #     ...
    # },
    # {
    #     'id':                      'oil_iraq',
    #     'commodity':               'oil',
    #     'country':                 'iraq',
    #     'trigger_signal_category': 'iraq_pipeline_disruption',
    #     'trigger_region':          'me',
    #     'commodity_threshold':     'high',
    #     'regions':                 ['me'],
    #     ...
    # },
    # NOTE: cobalt_drc has been ACTIVATED above as cobalt_drc_active (May 23 2026).
    # See the Africa / Belt-and-Road / Sanctions Convergences block.
]


# ════════════════════════════════════════════════════════════════════
# HELPERS — used by both Layer 1 (GPI) and Layer 2 (ME BLUF)
# ════════════════════════════════════════════════════════════════════

# Threshold ordering — higher index = more severe alert
_ALERT_ORDER = ['normal', 'elevated', 'high', 'surge']


def alert_meets_threshold(actual_alert, threshold):
    """
    Return True if the actual commodity alert level is at or above the
    configured threshold for this convergence.

    Examples:
        alert_meets_threshold('surge', 'elevated')   -> True
        alert_meets_threshold('elevated', 'surge')   -> False
        alert_meets_threshold('normal', 'elevated')  -> False
    """
    try:
        return _ALERT_ORDER.index(actual_alert) >= _ALERT_ORDER.index(threshold)
    except ValueError:
        return False


def find_convergence_by_country_commodity(country, commodity):
    """
    Layer 2 helper: when ME BLUF builds a country signal (e.g. lebanon humanitarian),
    look up whether any registered convergence applies to this country+commodity pair.

    Returns the registry dict if found, None otherwise.
    """
    for entry in CONVERGENCE_REGISTRY:
        if entry['country'] == country and entry['commodity'] == commodity:
            return entry
    return None


def find_convergences_for_country(country):
    """
    Layer 2 helper: list ALL convergences registered for a country.
    A country may have multiple convergence entries (e.g. wheat AND oil).

    Returns a list of registry dicts (possibly empty).
    """
    return [e for e in CONVERGENCE_REGISTRY if e['country'] == country]


def find_convergence_by_trigger(category, region):
    """
    Layer 1 helper: GPI sees a signal flowing from a regional BLUF and asks
    'is this signal a convergence trigger for any registered convergence?'

    Returns the registry dict if found, None otherwise.
    """
    for entry in CONVERGENCE_REGISTRY:
        if (entry['trigger_signal_category'] == category
            and entry['trigger_region'] == region):
            return entry
    return None


def format_headline(entry, alert_level):
    """Format the headline_template with the actual alert level."""
    return entry['headline_template'].format(alert=alert_level.upper())


def format_enrichment_text(entry, alert_level, signal_count):
    """Format the Layer 2 enrichment text template."""
    return entry['enrichment_text_template'].format(
        alert=alert_level.upper(),
        signals=signal_count,
    )
