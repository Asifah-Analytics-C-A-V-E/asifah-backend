"""
syria_signal_interpreter.py
Asifah Analytics -- ME Backend Module
v1.0.0

Signal interpretation engine for the Syria Rhetoric Tracker.

Syria's analytical frame is fundamentally different from Lebanon/Yemen/Iran.
Syria post-Assad is NOT an active conflict theatre -- it is a
TRANSITION STABILITY tracker. The key questions are:

  1. Is HTS consolidating legitimate governance or fragmenting?
  2. Is Turkey making territorial moves (SDF/Kurdish question)?
  3. Is Israel striking to prevent Iranian re-entry?
  4. Is ISIS exploiting the governance vacuum?
  5. Are the Druze (Suwayda) moving toward autonomy/independence?
  6. Will Syria normalize with Israel? (Abraham Accords angle)
  7. Is there a Kurdish political settlement or partition dynamic?

The SILENCE is analytically significant. Syria at L0/Monitoring
does NOT mean nothing is happening -- it means the transition is
holding. Score DROP is often GOOD news here (unlike every other tracker).

Key contextual factors:
  - HTS (Hayat Tahrir al-Sham) controls Damascus post-Assad Dec 2024
  - Ahmad al-Sharaa (Abu Mohammad al-Jolani) is interim leader
  - Israel has struck Syria 400+ times since Assad fell
  - Turkey backs SNA factions vs SDF/Kurds in northeast
  - Druze in Suwayda historically sought autonomy
  - US sanctions partially lifted -- economic normalization signals
  - Iran completely expelled from Syria -- supply corridor severed
  - Russia base status uncertain (Tartus/Hmeimim)

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# Syria frame: transition stability, not active conflict
# ============================================================
RED_LINES = [
    # ── Category A: HTS/Governance collapse ──────────────────
    {
        'id':       'hts_governance_collapse',
        'label':    'HTS Governance Collapse / Fragmentation',
        'detail':   'HTS loses control of Damascus or major cities -- transition collapses into factional war',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🏛️',
        'category': 'governance_trigger',
        'source':   'ISW; Carnegie Endowment Syria analysis -- governance vacuum historically triggers ISIS resurgence',
    },
    {
        'id':       'isis_major_resurgence',
        'label':    'ISIS Major Resurgence / Territory Seizure',
        'detail':   'ISIS seizes significant territory or conducts mass casualty attack in major city',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '☠️',
        'category': 'isis_trigger',
        'source':   'CENTCOM; ISW -- ISIS exploits governance vacuums; Deir ez-Zor and desert routes are key watch zones',
    },
    # ── Category B: Turkish/Kurdish escalation ────────────────
    {
        'id':       'turkish_major_offensive',
        'label':    'Turkish Military Major Offensive Against SDF',
        'detail':   'Turkey launches large-scale operation against SDF/AANES beyond current contact lines',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🇹🇷',
        'category': 'turkey_trigger',
        'source':   'NATO dynamics; CENTCOM Syria -- SDF is key US partner vs ISIS; Turkish offensive creates US-Turkey tension',
    },
    {
        'id':       'kurdish_partition_declaration',
        'label':    'Kurdish Autonomous Region Formal Declaration',
        'detail':   'SDF/AANES formally declares autonomous region or seeks international recognition',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🗺️',
        'category': 'kurdish_trigger',
        'source':   'Political analysis -- formal declaration would trigger Turkish military response and HTS opposition',
    },
    # ── Category C: Israeli strikes ───────────────────────────
    {
        'id':       'israel_escalation_beyond_strikes',
        'label':    'Israel Moves Beyond Strikes to Ground Presence',
        'detail':   'IDF establishes ground presence in Syria beyond current buffer zone -- territorial signal',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🔷',
        'category': 'israel_trigger',
        'source':   'IDF doctrine -- current strikes target weapons/infrastructure; ground presence = strategic shift',
    },
    {
        'id':       'iran_reentry_syria',
        'label':    'Iranian Forces / Proxies Re-Enter Syria',
        'detail':   'Confirmed IRGC or Iran-backed forces re-establish presence in Syria',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🕌',
        'category': 'iran_trigger',
        'source':   'Israel red line -- Iran expulsion from Syria is core Israeli strategic achievement post-Assad',
    },
    # ── Category D: Druze / minority signals ─────────────────
    {
        'id':       'druze_armed_uprising',
        'label':    'Druze Armed Uprising in Suwayda',
        'detail':   'Druze community takes up arms against HTS or central authority in Suwayda governorate',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🏔️',
        'category': 'druze_trigger',
        'source':   'Minority rights analysis -- Druze have historically avoided armed conflict but have self-defense capacity',
    },
    # ── Category E: Normalization signals (positive) ─────────
    {
        'id':       'syria_israel_normalization',
        'label':    'Syria-Israel Normalization Signal',
        'detail':   'HTS/Syrian government signals willingness to normalize with Israel -- Abraham Accords precedent',
        'severity': 1,
        'color':    '#3b82f6',
        'icon':     '🤝',
        'category': 'normalization_signal',
        'source':   'Diplomatic analysis -- al-Sharaa has signaled pragmatism; normalization would be transformative for region',
    },
    {
        'id':       'us_sanctions_lift',
        'label':    'US Full Sanctions Lift / Economic Normalization',
        'detail':   'US lifts Caesar Act sanctions -- enables economic reconstruction and HTS legitimization',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '💰',
        'category': 'normalization_signal',
        'source':   'Economic analysis -- sanctions are primary obstacle to Syrian reconstruction and HTS governance legitimacy',
    },
    {
        'id':       'hts_governance_consolidation',
        'label':    'HTS Governance Consolidation Signal',
        'detail':   'HTS demonstrates effective governance -- elections, constitution, minority protections',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '✅',
        'category': 'deescalation_signal',
        'source':   'Transition analysis -- governance consolidation is the key variable for Syria long-term stability',
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'isis_2014_emergence',
        'label':       'ISIS Territorial Emergence (2013-2014)',
        'description': 'ISIS exploited Syrian civil war governance vacuum to seize Raqqa and vast territory',
        'source':      'ISW; RAND Corporation; UN Security Council reports',
        'signals': {
            'governance_fragmented': True,
            'isis_level_min':        2,
            'us_engagement':         False,
        },
        'outcome':      'ISIS controlled 8M people across Syria/Iraq. Required 5-year military campaign to defeat. 100,000+ killed.',
        'window_hours': 720,
        'confidence':   'High',
    },
    {
        'id':          'assad_fall_dec_2024',
        'label':       'Assad Regime Collapse (December 2024)',
        'description': 'HTS-led offensive captured Damascus in 11 days -- 54-year Assad dynasty ended',
        'source':      'ISW; BBC; AP reporting December 2024',
        'signals': {
            'hts_offensive':         True,
            'governance_fragmented': True,
            'iran_present':          False,
            'russia_supporting':     False,
        },
        'outcome':      'HTS controls Damascus. Al-Sharaa interim leader. Iran expelled. Russia bases uncertain. Israel struck 400+ targets.',
        'window_hours': 0,
        'confidence':   'High',
    },
    {
        'id':          'israel_post_assad_strikes',
        'label':       'Israeli Systematic Strikes Post-Assad (Dec 2024-present)',
        'description': 'IDF struck Syrian military infrastructure to prevent weapons falling to hostile actors',
        'source':      'IDF statements; ISW; INSS analysis 2024-2025',
        'signals': {
            'israel_strike_level_min': 2,
            'iran_present':            False,
            'hts_governing':           True,
        },
        'outcome':      'Israel destroyed 80% of Syrian military assets. No HTS retaliation. De facto security understanding emerging.',
        'window_hours': 0,
        'confidence':   'High',
    },
    {
        'id':          'turkish_operation_euphrates',
        'label':       'Turkish Military Operations vs SDF (2016-present)',
        'description': 'Repeated Turkish operations against SDF/YPG in northern Syria',
        'source':      'RAND; ISW; Carnegie -- Turkey views SDF as PKK extension',
        'signals': {
            'turkey_level_min':  2,
            'sdf_territory':     True,
            'us_pressure_low':   True,
        },
        'outcome':      'Turkey seized Afrin (2018), northeast corridor (2019). SDF degraded but survives with US protection.',
        'window_hours': 168,
        'confidence':   'High',
    },
    {
        'id':          'druze_suwayda_protests',
        'label':       'Druze Suwayda Protests / Autonomy Signals (2023)',
        'description': 'Druze in Suwayda held sustained protests against Assad, signaling autonomy desire',
        'source':      'Chatham House; Syria Justice and Accountability Centre',
        'signals': {
            'druze_signals':         True,
            'governance_fragmented': True,
        },
        'outcome':      'Protests sustained for months. Druze maintained self-governance. No armed conflict. Autonomy question unresolved.',
        'window_hours': 336,
        'confidence':   'Medium',
    },
]


# ============================================================
# SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """Evaluate Syria signal state against red lines."""
    actors = scan_data.get('actors', {})

    hts_level    = actors.get('hts',          {}).get('escalation_level', 0)
    isis_level   = actors.get('isis',         {}).get('escalation_level', 0)
    turkey_level = actors.get('turkey',       {}).get('escalation_level', 0)
    sdf_level    = actors.get('sdf',          {}).get('escalation_level', 0)
    israel_level = actors.get('israel',       {}).get('escalation_level', 0)
    iran_level   = actors.get('iran_proxies', {}).get('escalation_level', 0)
    sna_level    = actors.get('sna',          {}).get('escalation_level', 0)
    us_level     = actors.get('us_envoy',     {}).get('escalation_level', 0)

    factional = scan_data.get('factional_level', 0)
    isis_vec  = scan_data.get('isis_level',      0)
    israel_vec= scan_data.get('israeli_strike_level', 0)
    theatre   = scan_data.get('theatre_score',   0)

    druze_signals = scan_data.get('druze_signals', [])
    hezbollah_nexus = scan_data.get('hezbollah_nexus_count', 0)

    def _scan(actor_ids, keywords):
        for aid in actor_ids:
            for art in actors.get(aid, {}).get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw in title for kw in keywords):
                    return True
        return False

    gov_collapse = _scan(['hts'], [
        'hts loses', 'collapse', 'infighting', 'fragmentation',
        'loses control', 'coup', 'overthrow', 'damascus falls'
    ])
    iran_reentry = _scan(['iran_proxies'], [
        'irgc returns', 'iran forces syria', 'hezbollah syria returns',
        'iranian troops', 'iran reestablish', 'proxy returns syria'
    ]) or hezbollah_nexus >= 3
    turkey_offensive = _scan(['turkey', 'sna'], [
        'turkish offensive', 'operation', 'turkey attacks sdf',
        'turkish forces advance', 'ankara launches', 'euphrates shield',
        'peace spring', 'turkish military operation'
    ])
    kurd_declaration = _scan(['sdf'], [
        'autonomous', 'independence', 'self-determination', 'federal',
        'kurdish state', 'aanes declares', 'recognition'
    ])
    israel_ground = _scan(['israel'], [
        'ground forces syria', 'idf enters syria', 'israeli troops',
        'idf advances', 'buffer zone expand', 'israeli ground'
    ])
    druze_armed = len(druze_signals) >= 3 or _scan(['hts', 'sdf'], [
        'druze armed', 'suwayda uprising', 'druze militia',
        'druze rebellion', 'suwayda fighting'
    ])
    normalization = _scan(['israel', 'us_envoy', 'hts'], [
        'normalize', 'normalization', 'peace deal', 'recognition israel',
        'abraham accords', 'syria israel talks', 'diplomatic relations',
        'partnership with syria', 'unprecedented partnership', 'syria against hezbollah',
        'israel syria cooperation', 'security cooperation syria', 'syria israel deal',
    ])
    sanctions_lift = _scan(['us_envoy', 'hts'], [
        'sanctions lifted', 'caesar act', 'sanctions relief',
        'economic normalization', 'remove sanctions', 'waive sanctions'
    ])
    hts_consolidating = _scan(['hts'], [
        'constitution', 'elections', 'minority protection',
        'reconciliation', 'governance', 'institution', 'legitimacy'
    ])
    isis_major = isis_vec >= 3 or _scan(['isis'], [
        'isis seizes', 'islamic state captures', 'isis controls',
        'mass casualty', 'isis attack city', 'caliphate'
    ])

    triggered = []

    # ── HTS governance collapse ──
    if gov_collapse or (factional >= 3 and hts_level <= 1):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hts_governance_collapse'),
            'status':  'BREACHED' if gov_collapse else 'APPROACHING',
            'trigger': f'Governance fragmentation signals + factional L{factional} -- HTS control under pressure',
        })

    # ── ISIS major resurgence ──
    if isis_major or isis_vec >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'isis_major_resurgence'),
            'status':  'BREACHED' if isis_major else 'APPROACHING',
            'trigger': f'ISIS vector L{isis_vec} -- resurgence signals in governance vacuum areas',
        })

    # ── Turkish offensive ──
    if turkey_offensive or (turkey_level >= 3 and sdf_level >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'turkish_major_offensive'),
            'status':  'BREACHED' if turkey_offensive else 'APPROACHING',
            'trigger': f'Turkey L{turkey_level}, SNA L{sna_level} -- offensive operation language detected',
        })

    # ── Kurdish declaration ──
    if kurd_declaration and sdf_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'kurdish_partition_declaration'),
            'status':  'APPROACHING',
            'trigger': 'Kurdish autonomy/recognition language detected -- would trigger Turkish response',
        })

    # ── Israel beyond strikes ──
    if israel_ground or (israel_vec >= 4):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'israel_escalation_beyond_strikes'),
            'status':  'BREACHED' if israel_ground else 'APPROACHING',
            'trigger': f'IDF L{israel_level}, strike vector L{israel_vec} -- ground presence signals',
        })

    # ── Iran re-entry ──
    if iran_reentry or iran_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'iran_reentry_syria'),
            'status':  'BREACHED' if iran_reentry else 'APPROACHING',
            'trigger': f'Iran proxy L{iran_level} + Hezbollah nexus signals ({hezbollah_nexus}) -- re-entry attempt',
        })

    # ── Druze armed uprising ──
    if druze_armed:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'druze_armed_uprising'),
            'status':  'APPROACHING',
            'trigger': f'{len(druze_signals)} Druze/Suwayda signals -- armed mobilization language detected',
        })

    # ── Normalization signal (blue -- informational) ──
    if normalization:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'syria_israel_normalization'),
            'status':  'APPROACHING',
            'trigger': 'Syria-Israel normalization language detected -- diplomatic track signal',
        })

    # ── Sanctions lift (green) ──
    if sanctions_lift:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_sanctions_lift'),
            'status':  'APPROACHING',
            'trigger': 'US sanctions relief language -- Caesar Act / economic normalization signal',
        })

    # ── HTS consolidation (green) ──
    if hts_consolidating:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hts_governance_consolidation'),
            'status':  'APPROACHING',
            'trigger': 'HTS governance consolidation signals -- constitution/elections/minority language',
        })

    triggered.sort(key=lambda x: (
        0 if x['status'] == 'BREACHED' else 1,
        -x['severity'],
        0 if x['category'] not in ('normalization_signal', 'deescalation_signal') else 1
    ))
    return triggered


def _match_historical(scan_data):
    """Match Syria signal state against historical precedents."""
    actors = scan_data.get('actors', {})

    isis_vec     = scan_data.get('isis_level',            0)
    factional    = scan_data.get('factional_level',       0)
    israel_vec   = scan_data.get('israeli_strike_level',  0)
    turkey_level = actors.get('turkey', {}).get('escalation_level', 0)
    sdf_level    = actors.get('sdf',    {}).get('escalation_level', 0)
    iran_level   = actors.get('iran_proxies', {}).get('escalation_level', 0)
    druze        = len(scan_data.get('druze_signals', []))
    hts_level    = actors.get('hts', {}).get('escalation_level', 0)

    gov_fragmented = factional >= 2 or hts_level <= 1
    hts_governing  = hts_level >= 1
    iran_present   = iran_level >= 2
    us_engaged     = actors.get('us_envoy', {}).get('statement_count', 0) >= 3

    matches = []

    for precedent in HISTORICAL_PRECEDENTS:
        sigs = precedent['signals']
        score = 0
        max_score = 0
        matched = []
        missed = []

        def check(condition, label, weight=1):
            nonlocal score, max_score
            max_score += weight
            if condition:
                score += weight
                matched.append(label)
            else:
                missed.append(label)

        if 'governance_fragmented' in sigs:
            check(gov_fragmented == sigs['governance_fragmented'],
                  f'Governance fragmented: {gov_fragmented}', weight=2)
        if 'isis_level_min' in sigs:
            check(isis_vec >= sigs['isis_level_min'],
                  f'ISIS L{isis_vec} >= L{sigs["isis_level_min"]}', weight=3)
        if 'us_engagement' in sigs:
            check(us_engaged == sigs['us_engagement'],
                  f'US engagement: {us_engaged}', weight=1)
        if 'hts_governing' in sigs:
            check(hts_governing == sigs['hts_governing'],
                  f'HTS governing: {hts_governing}', weight=2)
        if 'iran_present' in sigs:
            check(iran_present == sigs['iran_present'],
                  f'Iran present: {iran_present}', weight=2)
        if 'israel_strike_level_min' in sigs:
            check(israel_vec >= sigs['israel_strike_level_min'],
                  f'IDF strikes L{israel_vec}', weight=2)
        if 'turkey_level_min' in sigs:
            check(turkey_level >= sigs['turkey_level_min'],
                  f'Turkey L{turkey_level}', weight=2)
        if 'sdf_territory' in sigs:
            check(sdf_level >= 1, 'SDF active', weight=1)
        if 'druze_signals' in sigs:
            check(druze >= 1, f'{druze} Druze signals', weight=1)

        if max_score == 0:
            continue
        similarity = round((score / max_score) * 100)
        if similarity >= 40:
            matches.append({
                'id':              precedent['id'],
                'label':           precedent['label'],
                'description':     precedent['description'],
                'source':          precedent['source'],
                'outcome':         precedent['outcome'],
                'window_hours':    precedent['window_hours'],
                'confidence':      precedent['confidence'],
                'similarity':      similarity,
                'matched_signals': matched,
                'missed_signals':  missed,
            })

    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]


def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Syria command node assessment.
    Frame: TRANSITION STABILITY tracker -- silence can be good news.
    Key questions: HTS consolidation, Turkey/Kurd, Israel strikes,
    ISIS watch, Druze autonomy, normalization potential.
    """
    actors = scan_data.get('actors', {})

    hts_level    = actors.get('hts',          {}).get('escalation_level', 0)
    isis_vec     = scan_data.get('isis_level',            0)
    factional    = scan_data.get('factional_level',       0)
    israel_vec   = scan_data.get('israeli_strike_level',  0)
    turkey_level = actors.get('turkey', {}).get('escalation_level', 0)
    iran_level   = actors.get('iran_proxies', {}).get('escalation_level', 0)
    druze        = len(scan_data.get('druze_signals', []))
    theatre      = scan_data.get('theatre_score', 0)
    hezbollah_nexus = scan_data.get('hezbollah_nexus_count', 0)

    delta = scan_data.get('delta', {}) or {}
    delta_dir    = delta.get('direction', 'stable')
    score_change = delta.get('score_change', 0)

    breached_count   = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    approaching_count= sum(1 for r in red_lines_triggered if r['status'] == 'APPROACHING')
    top_match        = historical_matches[0] if historical_matches else None

    normalization_active = any(r['id'] == 'syria_israel_normalization' for r in red_lines_triggered)
    sanctions_active     = any(r['id'] == 'us_sanctions_lift'          for r in red_lines_triggered)
    hts_consolidating    = any(r['id'] == 'hts_governance_consolidation' for r in red_lines_triggered)
    iran_expelled        = iran_level <= 1

    # ── Scenario label ──
    if breached_count >= 2 or factional >= 4 or isis_vec >= 4:
        scenario       = 'CRITICAL -- Transition Collapse Risk'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif breached_count == 1 or factional >= 2 or turkey_level >= 3:
        scenario       = 'ELEVATED -- Transition Stress Signals'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif normalization_active or sanctions_active or hts_consolidating:
        scenario       = 'POSITIVE -- Normalization / Consolidation Signals'
        scenario_color = '#10b981'
        scenario_icon  = '🟢'
    elif theatre <= 10 and delta_dir in ('stable', 'falling'):
        scenario       = 'MONITORING -- Transition Holding, Low Signal Environment'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'
    else:
        scenario       = 'MONITORING -- Below Escalation Threshold'
        scenario_color = '#3b82f6'
        scenario_icon  = '🔵'

    # ── Situation ──
    situation_parts = []

    if theatre <= 10:
        situation_parts.append(
            'Syria is in a LOW SIGNAL environment -- analytically this is expected for a post-conflict '
            'transition phase. Low score does NOT mean nothing is happening; it means the transition is '
            'holding below the escalation threshold. The silence of HTS and Israeli actors is notable: '
            'a de facto security understanding may be emerging between Jerusalem and Damascus.'
        )
    elif theatre <= 30:
        situation_parts.append(
            f'Syria at {theatre}/100 -- transition phase signals. Monitor for ISIS exploitation '
            f'of governance gaps and Turkish posture toward SDF.'
        )

    if iran_expelled:
        situation_parts.append(
            'Iran has been effectively expelled from Syria -- a major Israeli strategic achievement. '
            'The Syria-Lebanon weapons corridor that supplied Hezbollah for decades is severed. '
            'Any Iranian re-entry attempt would immediately trigger Israeli strikes.'
        )

    if israel_vec >= 2:
        situation_parts.append(
            f'IDF strike activity at L{israel_vec} -- Israel has struck 400+ targets in Syria since '
            f'Assad fell, systematically destroying military infrastructure. HTS has not retaliated, '
            f'suggesting a tacit understanding: HTS accepts Israeli strikes on pre-Assad weapons; '
            f'Israel accepts HTS governance.'
        )

    if turkey_level >= 2:
        situation_parts.append(
            f'Turkey at L{turkey_level} -- Ankara is the most active external power in Syria now. '
            f'The SDF/Kurdish question is the primary unresolved conflict driver. '
            f'US protection of SDF (key ISIS partner) creates persistent US-Turkey friction.'
        )

    if druze >= 1:
        situation_parts.append(
            f'{druze} Druze/Suwayda signals detected. The Druze question -- autonomy vs integration '
            f'under HTS -- remains unresolved. Druze have historically avoided armed conflict '
            f'but have self-defense capacity and Israeli sympathy.'
        )

    if delta_dir == 'falling':
        situation_parts.append(
            f'Score falling ({round(score_change)} pts from recent average) -- de-escalation trajectory. '
            f'In Syria context, a falling score is analytically positive.'
        )

    # ── Key indicators ──
    indicators = []

    indicators.append(
        'TRANSITION STABILITY FRAME: Unlike other trackers, Syria L0/Monitoring is NOT a failure mode. '
        'The key question is whether HTS is consolidating legitimate governance. '
        'Watch: constitution drafting, minority protections, economic activity resumption.'
    )

    if not iran_expelled:
        indicators.append(
            'IRAN RE-ENTRY WATCH: Any confirmed IRGC or proxy return to Syria is the highest-priority '
            'signal -- would immediately trigger Israeli escalation and collapse the tacit HTS-Israel understanding.'
        )
    else:
        indicators.append(
            'IRAN EXPELLED (positive): Iran-Syria corridor severed. Hezbollah resupply route eliminated. '
            'This is a major regional shift -- sustaining Iranian exclusion is Syria\'s most important '
            'contribution to regional stability right now.'
        )

    indicators.append(
        'NORMALIZATION WATCH: Ahmad al-Sharaa has signaled pragmatism. '
        'Syria-Israel normalization -- even tacit -- would be transformative. '
        'Abraham Accords precedent: US economic incentives could accelerate this track.'
    )

    indicators.append(
        'ISIS EXPLOITATION WINDOW: Post-Assad transition creates the governance vacuum ISIS '
        'historically exploits. Deir ez-Zor, the Syrian desert, and areas outside HTS control '
        'are the key watch zones. US CENTCOM and SDF partnership is the primary counter.'
    )

    # ── Assessment ──
    assessment_parts = []

    if top_match and top_match['similarity'] >= 50:
        assessment_parts.append(
            f'Current pattern shows {top_match["similarity"]}% similarity to {top_match["label"]}. '
            f'In that case: {top_match["outcome"].lower()}'
        )

    if theatre <= 10:
        assessment_parts.append(
            'Low signal environment reflects early transition stability -- not complacency. '
            'The most important near-term indicators are: (1) HTS governance delivery, '
            '(2) Kurdish political settlement progress, (3) ISIS activity in desert zones, '
            '(4) any Iranian re-entry attempt.'
        )

    # ── Watch list ──
    watch_items = [
        'HTS governance delivery -- constitution, elections, minority rights signals',
        'Iranian re-entry attempt -- any IRGC/proxy signals in Syria immediately escalatory',
        'ISIS activity in Deir ez-Zor and Syrian desert -- primary exploitation zone',
        'Turkey-SDF contact lines -- any Turkish offensive preparation language',
        'Druze Suwayda signals -- autonomy vs HTS integration dynamic',
        'Syria-Israel normalization signals -- tacit understanding becoming explicit?',
        'US sanctions (Caesar Act) status -- economic normalization prerequisite',
    ]

    return {
        'scenario':                scenario,
        'scenario_color':          scenario_color,
        'scenario_icon':           scenario_icon,
        'situation':               ' '.join(situation_parts),
        'key_indicators':          indicators[:4],
        'assessment':              ' '.join(assessment_parts),
        'watch_list':              watch_items[:5],
        'iran_expelled':           iran_expelled,
        'normalization_active':    normalization_active,
        'low_signal_is_positive':  theatre <= 15,
        'generated_at':            datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Syria assessment generated from open-source signal data. '
            'IMPORTANT: Low score in Syria is analytically different from other trackers -- '
            'it reflects transition stability, not absence of significance. '
            'Not a prediction. Verify through official channels.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """Main entry point. Called from rhetoric_tracker_syria.py."""
    try:
        red_lines  = _score_red_lines(scan_data)
        historical = _match_historical(scan_data)
        so_what    = _build_so_what(scan_data, red_lines, historical)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']

        return {
            'so_what':             so_what,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'historical_matches':  historical,
            'interpreter_version': '1.0.0',
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Syria Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [],
            'interpreter_version': '1.0.0',
            'error':              str(e)[:200],
        }


# ============================================================
# CANONICAL TOP_SIGNALS BUILDER — v2.0 (April 2026)
# ============================================================
# Emits the canonical schema for Syria signals that feeds:
#   - ME Regional BLUF (me_regional_bluf.py)
#   - Global Pressure Index (global_pressure_index.py)
#
# CRITICAL ARCHITECTURAL NOTE:
# Syria is INVERTED-LOGIC compared to other ME trackers. Low scores here
# mean the transition is HOLDING -- which is GOOD news. So instead of
# spamming "theatre_high" signals when Syria is at L0/L1, we emit a
# "diplomatic_active" / "transition_stable" positive-news signal.
#
# Signals are escalation-driven only when actual instability triggers fire.
#
# Signal shape (canonical across platform):
# {
#     'priority':   int,
#     'category':   str,        # red_line_breached / kinetic_pressure / theatre_high /
#                               #   regime_fracture / diplomatic_active / silence_anomaly /
#                               #   crosstheater_iran_syria
#     'theatre':    'syria',
#     'level':      int,        # 0-5
#     'icon':       str,
#     'color':      str,
#     'short_text': str,        # ≤80 char
#     'long_text':  str,        # ≤200 char
# }

SYRIA_FLAG = '\U0001f1f8\U0001f1fe'  # 🇸🇾


def build_top_signals(result):
    """
    Build Syria's top_signals[] for BLUF/GPI consumption.
    Reads from a fully-built scan result (with interpretation attached).
    Returns sorted list (descending priority); BLUF/GPI dedupes globally.
    """
    signals = []

    theatre_level = result.get('theatre_level',
                    result.get('theatre_escalation_level', 0)) or 0
    theatre_score = result.get('theatre_score', 0) or 0

    # Syria-specific vectors
    factional_lvl = result.get('factional_level',      0) or 0
    strikes_lvl   = result.get('israeli_strike_level', 0) or 0
    isis_lvl      = result.get('isis_level',           0) or 0

    actors = result.get('actors', {}) or {}
    hts_lvl          = actors.get('hts',          {}).get('escalation_level', 0)
    sdf_lvl          = actors.get('sdf',          {}).get('escalation_level', 0)
    sna_lvl          = actors.get('sna',          {}).get('escalation_level', 0)
    turkey_lvl       = actors.get('turkey',       {}).get('escalation_level', 0)
    israel_lvl       = actors.get('israel',       {}).get('escalation_level', 0)
    iran_proxies_lvl = actors.get('iran_proxies', {}).get('escalation_level', 0)
    us_envoy_lvl     = actors.get('us_envoy',     {}).get('escalation_level', 0)

    druze_signal_count    = result.get('druze_signals_count', 0) or len(result.get('druze_signals', []))
    hezbollah_nexus_count = result.get('hezbollah_nexus_count', 0)

    # Pull interpretation block
    interp = result.get('interpretation', {}) or {}
    so_what = interp.get('so_what', {}) or {}
    rl_obj  = interp.get('red_lines', {}) or {}

    iran_expelled         = so_what.get('iran_expelled', False)
    normalization_active  = so_what.get('normalization_active', False)
    low_signal_positive   = so_what.get('low_signal_is_positive', False)

    # ============================================
    # CATEGORY 1: RED LINES BREACHED (highest priority)
    # ============================================
    for rl in rl_obj.get('triggered', []):
        if rl.get('status') == 'BREACHED':
            severity = int(rl.get('severity', 0) or 0)
            signals.append({
                'priority':   12 if severity >= 3 else 11,
                'category':   'red_line_breached',
                'theatre':    'syria',
                'level':      max(theatre_level, severity * 2),
                'icon':       rl.get('icon', '🚨'),
                'color':      '#dc2626',
                'short_text': f'{SYRIA_FLAG} SYRIA: {rl.get("label", "Red line breached")[:60]}',
                'long_text':  (f'SYRIA red line breached -- {rl.get("label", "")}: '
                               f'{rl.get("trigger", "")[:140]}'),
            })

    # ============================================
    # CATEGORY 2: TURKEY-SDF KINETIC PRESSURE (Kurdish question)
    # ============================================
    if turkey_lvl >= 3 and sdf_lvl >= 2:
        signals.append({
            'priority':   11,
            'category':   'kinetic_pressure',
            'theatre':    'syria',
            'level':      max(turkey_lvl, sdf_lvl),
            'icon':       '⚔️',
            'color':      '#dc2626',
            'short_text': f'{SYRIA_FLAG} SYRIA: Turkey-SDF tension (L{max(turkey_lvl, sdf_lvl)})',
            'long_text':  (f'SYRIA: Turkish military posture vs Syrian Democratic Forces (SDF) '
                           f'elevated. Northeastern Syria Kurdish question reactivating; '
                           f'potential offensive prep language detected.'),
        })

    # ============================================
    # CATEGORY 3: ISRAELI STRIKES (Iran prevention vector)
    # ============================================
    if strikes_lvl >= 3:
        signals.append({
            'priority':   10,
            'category':   'kinetic_pressure',
            'theatre':    'syria',
            'level':      strikes_lvl,
            'icon':       '🎯',
            'color':      '#f97316',
            'short_text': f'{SYRIA_FLAG} SYRIA: Israeli airstrikes elevated (L{strikes_lvl})',
            'long_text':  (f'SYRIA: Israeli airstrike tempo at L{strikes_lvl} -- southern '
                           f'Syria / Damascus periphery. Iranian Revolutionary Guard Corps '
                           f'(IRGC) re-entry prevention posture; Golan-proximity activity.'),
        })

    # ============================================
    # CATEGORY 4: ISIS RECONSTITUTION (governance vacuum exploitation)
    # ============================================
    if isis_lvl >= 3:
        signals.append({
            'priority':   10,
            'category':   'kinetic_pressure',
            'theatre':    'syria',
            'level':      isis_lvl,
            'icon':       '⚫',
            'color':      '#1f2937',
            'short_text': f'{SYRIA_FLAG} SYRIA: Islamic State (ISIS) reconstitution L{isis_lvl}',
            'long_text':  (f'SYRIA: Islamic State (ISIS) reconstitution signals at L{isis_lvl} '
                           f'across Idlib desert, Sinjar, and former territory. Hayat Tahrir '
                           f'al-Sham (HTS) governance vacuum being exploited.'),
        })

    # ============================================
    # CATEGORY 5: HTS FRAGMENTATION (regime fracture)
    # ============================================
    if factional_lvl >= 4:
        signals.append({
            'priority':   10,
            'category':   'regime_fracture',
            'theatre':    'syria',
            'level':      factional_lvl,
            'icon':       '⚡',
            'color':      '#ef4444',
            'short_text': f'{SYRIA_FLAG} SYRIA: HTS factional stress (L{factional_lvl})',
            'long_text':  (f'SYRIA: Hayat Tahrir al-Sham (HTS) factional fragmentation '
                           f'signals at L{factional_lvl}. Damascus governance consolidation '
                           f'failing; competing factions visible.'),
        })

    # ============================================
    # CATEGORY 6: DRUZE AUTONOMY MOVEMENT (Suwayda dynamics)
    # ============================================
    if druze_signal_count >= 3:
        signals.append({
            'priority':   9,
            'category':   'regime_fracture',
            'theatre':    'syria',
            'level':      3,
            'icon':       '🟣',
            'color':      '#8b5cf6',
            'short_text': f'{SYRIA_FLAG} SYRIA: Druze (Suwayda) autonomy signals',
            'long_text':  (f'SYRIA: Druze community in Suwayda showing autonomy / '
                           f'self-defense organizing signals ({druze_signal_count} signals). '
                           f'Israel-Druze coordination dynamic active.'),
        })

    # ============================================
    # CATEGORY 7: HEZBOLLAH-SYRIA NEXUS (cross-theater fingerprint)
    # ============================================
    if hezbollah_nexus_count >= 2:
        signals.append({
            'priority':   10,
            'category':   'crosstheater_iran_syria',
            'theatre':    'syria',
            'level':      max(iran_proxies_lvl, 3),
            'icon':       '🔗',
            'color':      '#7c3aed',
            'short_text': f'{SYRIA_FLAG} SYRIA: Hezbollah-Syria nexus active',
            'long_text':  (f'SYRIA: Hezbollah cross-pollination signals ({hezbollah_nexus_count} '
                           f'detections). Iran proxy network using Syria-Lebanon corridor; '
                           f'cross-theater coordination fingerprint active.'),
        })

    # ============================================
    # CATEGORY 8: THEATRE COMPOSITE HIGH (catch-all when escalating)
    # ============================================
    if theatre_level >= 4 or theatre_score >= 70:
        signals.append({
            'priority':   9,
            'category':   'theatre_high',
            'theatre':    'syria',
            'level':      theatre_level,
            'icon':       '🔴',
            'color':      '#dc2626',
            'short_text': f'{SYRIA_FLAG} SYRIA: Theatre composite L{theatre_level} ({theatre_score}/100)',
            'long_text':  (f'SYRIA composite rhetoric at L{theatre_level} '
                           f'(score {theatre_score}/100). Multi-vector escalation; transition '
                           f'stability at risk.'),
        })

    # ============================================
    # CATEGORY 9: TRANSITION STABLE (Syria-specific INVERTED-LOGIC positive signal)
    # ============================================
    # Only emit if NO escalation signals already fired.
    # This is the unique Syria pattern: low-signal IS positive.
    if not signals and low_signal_positive and theatre_level <= 1:
        signals.append({
            'priority':   5,
            'category':   'diplomatic_active',
            'theatre':    'syria',
            'level':      0,
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': f'{SYRIA_FLAG} SYRIA: Transition holding (L0 monitoring)',
            'long_text':  (f'SYRIA post-Assad transition stability holding (score '
                           f'{theatre_score}/100). HTS governance consolidation continuing; '
                           f'no major fragmentation, kinetic, or proxy escalation detected.'),
        })

    # ============================================
    # CATEGORY 10: IRAN EXPELLED (positive structural signal)
    # ============================================
    if iran_expelled:
        signals.append({
            'priority':   7,
            'category':   'diplomatic_active',
            'theatre':    'syria',
            'level':      0,
            'icon':       '✅',
            'color':      '#10b981',
            'short_text': f'{SYRIA_FLAG} SYRIA: Iran expelled (structural positive)',
            'long_text':  (f'SYRIA: Iranian Revolutionary Guard Corps (IRGC) and proxy '
                           f'presence reduced post-Assad. Structural strategic shift -- '
                           f'land-bridge to Hezbollah severed.'),
        })

    # ============================================
    # CATEGORY 11: NORMALIZATION TRACK (Syria-Israel dialogue)
    # ============================================
    if normalization_active:
        signals.append({
            'priority':   8,
            'category':   'diplomatic_active',
            'theatre':    'syria',
            'level':      0,
            'icon':       '🤝',
            'color':      '#10b981',
            'short_text': f'{SYRIA_FLAG} SYRIA: Normalization track signals (positive)',
            'long_text':  (f'SYRIA: Tacit Syria-Israel normalization signals detected. '
                           f'Abraham Accords angle opening; US envoy facilitation '
                           f'(Caesar Act sanctions discussion) supportive.'),
        })

    # Sort descending by priority
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    test_data = {
        'theatre_score':         5,
        'factional_level':       0,
        'isis_level':            0,
        'israeli_strike_level':  1,
        'druze_signals':         [],
        'hezbollah_nexus_count': 0,
        'delta': {'direction': 'falling', 'score_change': -27},
        'actors': {
            'hts':          {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'isis':         {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'turkey':       {'escalation_level': 0, 'statement_count': 2, 'top_articles': []},
            'sdf':          {'escalation_level': 0, 'statement_count': 1, 'top_articles': []},
            'sna':          {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'israel':       {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'iran_proxies': {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'us_envoy':     {'escalation_level': 0, 'statement_count': 1, 'top_articles': [
                {'title': 'US discusses lifting Caesar Act sanctions on Syria with HTS', 'published': ''},
            ]},
        },
    }

    result = interpret_signals(test_data)
    sw = result['so_what']
    print('\n' + '='*65)
    print(f'SCENARIO: {sw["scenario"]}')
    print(f'IRAN EXPELLED: {sw.get("iran_expelled")}')
    print(f'LOW SIGNAL POSITIVE: {sw.get("low_signal_is_positive")}')
    print('='*65)
    print('\nSITUATION:')
    print(sw['situation'][:500])
    print('\nKEY INDICATORS:')
    for ind in sw['key_indicators']:
        print(f'  -- {ind[:100]}')
    print('\nWATCH LIST:')
    for item in sw['watch_list']:
        print(f'  -> {item}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} [{rl["category"]}]')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]}')
