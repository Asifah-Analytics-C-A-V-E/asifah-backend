"""
lebanon_signal_interpreter.py
Asifah Analytics -- ME Backend Module
v1.0.0

Signal interpretation engine for the Lebanon Rhetoric Tracker.

Lebanon's analytical frame is fundamentally three-way:

  1. Is Hezbollah re-activating under Iranian direction
     (not in defense of Lebanon -- in service of the axis)?
  2. Is Israel going to stay in southern Lebanon, expand,
     or can conditions be created for withdrawal?
  3. Will the LAF/GOL ever actually enforce 1701 and give
     Israel confidence to pull back?

Key contextual factors baked in:
  - Hezbollah entered the war March 2, 2026 on Iran's direction
  - Radwan forces surrendered -- morale signal, sent to die
  - IDF is in south Lebanon creating a buffer zone (Gaza yellow zone model)
  - LAF is largely toothless -- deployment vs. enforcement is different
  - Lebanese Shia public opinion is diverging from Hezbollah
  - Post-Nasrallah Hezbollah is weaker but still armed
  - Syria corridor for re-arming is now contested (post-Assad HTS control)
  - The question: what would GOL/LAF need to DO for Israel to feel safe leaving?

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [
    # ── Category A: Hezbollah re-activation triggers ─────────
    {
        'id':       'hezbollah_military_reactivation',
        'label':    'Hezbollah Military Wing Re-Activation',
        'detail':   'Hezbollah military (Radwan/Islamic Resistance) resumes offensive operations after ceasefire',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '⚔️',
        'category': 'hezbollah_trigger',
        'source':   'Israeli doctrine -- Hezbollah offensive ops trigger automatic IDF response; ceasefire collapse signal',
    },
    {
        'id':       'litani_violation',
        'label':    'Hezbollah Armed Presence South of Litani',
        'detail':   'Hezbollah forces or weapons confirmed south of Litani River -- core Israeli red line under 1701',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🌊',
        'category': 'hezbollah_trigger',
        'source':   'UNSCR 1701; Israeli stated red line -- Litani River is the IDF withdrawal condition',
    },
    {
        'id':       'iran_weapons_resupply',
        'label':    'Iranian Weapons Resupply to Hezbollah',
        'detail':   'Confirmed or credible report of Iranian weapons transfer through Syria corridor to Hezbollah',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '📦',
        'category': 'iran_coordination',
        'source':   'Pattern analysis -- resupply attempts historically preceded escalation cycles',
    },
    {
        'id':       'idf_buffer_zone_expansion',
        'label':    'IDF Buffer Zone Expansion in Lebanon',
        'detail':   'IDF expands beyond current buffer zone -- signals Israeli intent to hold territory longer',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🗺️',
        'category': 'israel_trigger',
        'source':   'Gaza yellow zone precedent -- expansion signals failure of diplomatic withdrawal conditions',
    },
    {
        'id':       'qassem_military_authorization',
        'label':    'Qassem Issues Military Authorization Signal',
        'detail':   'Naim Qassem shifts from political to military language -- authorization signal for operations',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '👁️',
        'category': 'hezbollah_trigger',
        'source':   'Pattern analysis -- Qassem political-to-military language shift preceded Hezbollah ops in 2024',
    },
    {
        'id':       'laf_enforcement_failure',
        'label':    'LAF Fails to Deploy / Enforce 1701',
        'detail':   'Lebanese Armed Forces refuse or fail to deploy south of Litani -- removes Israeli withdrawal condition',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🏳️',
        'category': 'laf_signal',
        'source':   'Israeli withdrawal condition -- LAF enforcement of 1701 is the key diplomatic ask',
    },
    {
        'id':       'unifil_withdrawal',
        'label':    'UNIFIL Withdrawal or Evacuation',
        'detail':   'UNIFIL forces withdraw or reduce -- removes buffer, historically precedes escalation',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🇺🇳',
        'category': 'international_signal',
        'source':   'Historical pattern -- UNIFIL withdrawal signals international loss of confidence in ceasefire',
    },
    {
        'id':       'shia_public_dissent',
        'label':    'Lebanese Shia Public Distancing from Hezbollah',
        'detail':   'Credible signals of Shia community dissent from Hezbollah -- weakens Hezbollah legitimacy claim',
        'severity': 1,
        'color':    '#06b6d4',
        'icon':     '👥',
        'category': 'domestic_signal',
        'source':   'Political analysis -- Hezbollah claims to protect Lebanon; Shia dissent undermines this framing',
    },
    {
        'id':       'idf_ultimatum_gol',
        'label':    'IDF/Israel Issues Ultimatum to GOL',
        'detail':   'Israel issues direct ultimatum to Lebanese government re: Hezbollah disarmament or LAF deployment',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '⏱️',
        'category': 'israel_trigger',
        'source':   'Escalation pattern -- Israeli ultimatums to GOL historically preceded kinetic action',
    },
    {
        'id':       'laf_enforces_south',
        'label':    'LAF Actively Enforces South Lebanon',
        'detail':   'LAF deploys and actively enforces 1701 south of Litani -- key Israeli withdrawal condition met',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '✅',
        'category': 'deescalation_signal',
        'source':   'Israeli withdrawal condition -- genuine LAF enforcement is the diplomatic off-ramp',
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'second_lebanon_war_2006',
        'label':       'Second Lebanon War (July 2006)',
        'description': 'Hezbollah cross-border raid and kidnapping triggered full IDF invasion',
        'source':      'IISS; ISW; Winograd Commission report 2008',
        'signals': {
            'hezbollah_military_min': 4,
            'israel_level_min':       4,
            'laf_enforcement':        False,
            'unifil_present':         True,
        },
        'outcome':      '34-day war. UNSCR 1701 adopted. Hezbollah survived but significantly degraded. LAF deployed but never enforced.',
        'window_hours': 48,
        'confidence':   'High',
    },
    {
        'id':          'nasrallah_assassination_2024',
        'label':       'Nasrallah Assassination and Lebanon War (Sept 2024)',
        'description': 'IDF killed Nasrallah, ground operation in south Lebanon, ceasefire Nov 2024',
        'source':      'ISW; INSS; IISS Strategic Comments 2024',
        'signals': {
            'hezbollah_military_min': 4,
            'israel_level_min':       5,
            'iran_coordination':      True,
            'laf_enforcement':        False,
        },
        'outcome':      'Hezbollah severely degraded. Nasrallah and most senior leadership killed. Ceasefire Nov 27, 2024. IDF remained in south.',
        'window_hours': 72,
        'confidence':   'High',
    },
    {
        'id':          'march_2026_reactivation',
        'label':       'Hezbollah Re-Activation (March 2, 2026)',
        'description': 'Hezbollah resumed missile fire on Israel on Iran direction -- not Lebanese defense',
        'source':      'Asifah Analytics current pattern; Radwan surrender signals; Iranian direction confirmed',
        'signals': {
            'hezbollah_military_min': 3,
            'iran_coordination':      True,
            'israel_level_min':       3,
            'laf_enforcement':        False,
        },
        'outcome':      'IDF operating in south Lebanon buffer zone. Hezbollah fighting on Iranian direction. Radwan morale degraded -- surrender signals.',
        'window_hours': 96,
        'confidence':   'Medium',
    },
    {
        'id':          'iran_resupply_interdiction',
        'label':       'Iran Weapons Resupply Attempts (2023-2025)',
        'description': 'Repeated Israeli strikes on Syria-Lebanon weapons corridor to interdict resupply',
        'source':      'CSIS; ISW; IDF statements 2023-2025',
        'signals': {
            'iran_coordination':      True,
            'hezbollah_military_min': 2,
            'israel_level_min':       2,
        },
        'outcome':      'IDF struck dozens of weapons transfers. Syria corridor degraded post-Assad but not eliminated. HTS now controls key routes.',
        'window_hours': 168,
        'confidence':   'High',
    },
    {
        'id':          'laf_1701_precedent',
        'label':       'LAF 1701 Deployment Without Enforcement (2006-2026)',
        'description': 'LAF deployed south after 2006 but never enforced against Hezbollah for 20 years',
        'source':      'UN Panel of Experts; Chatham House; Carnegie Endowment Lebanon analysis',
        'signals': {
            'laf_enforcement':        False,
            'hezbollah_military_min': 2,
            'unifil_present':         True,
        },
        'outcome':      'Two-decade pattern: LAF presence without enforcement enabled Hezbollah rebuild. Israel never withdrew conditions met.',
        'window_hours': 0,
        'confidence':   'High',
    },
]


# ============================================================
# CORE SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """Evaluate Lebanon signal state against red lines."""
    actors = scan_data.get('actors', {})

    hezb_pol_level  = actors.get('hezbollah_political', {}).get('escalation_level', 0)
    hezb_mil_level  = actors.get('hezbollah_military',  {}).get('escalation_level', 0)
    iran_level      = actors.get('iran_lebanon',        {}).get('escalation_level', 0)
    israel_level    = actors.get('israel_lebanon',      {}).get('escalation_level', 0)
    laf_level       = actors.get('lebanese_government', {}).get('escalation_level', 0)
    unifil_level    = actors.get('unifil',              {}).get('escalation_level', 0)

    ground_ops  = scan_data.get('ground_ops_level',  0)
    rockets     = scan_data.get('rockets_level',     0)
    ceasefire   = scan_data.get('ceasefire_level',   0)
    crossborder = scan_data.get('crossborder_level', 0)
    theatre_score = scan_data.get('rhetoric_score', scan_data.get('theatre_score', 0))

    # Check article text for key signals
    def _scan_articles(actor_ids, keywords):
        for aid in actor_ids:
            for art in actors.get(aid, {}).get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw in title for kw in keywords):
                    return True
        return False

    litani_signal = _scan_articles(
        ['hezbollah_military', 'israel_lebanon'],
        ['litani', 'south of litani', 'below litani', 'north of litani', 'litani river']
    )
    resupply_signal = _scan_articles(
        ['iran_lebanon', 'syria_border', 'hezbollah_military'],
        ['weapons', 'arms', 'smuggling', 'resupply', 'transfer', 'corridor', 'shipment']
    )
    buffer_zone_signal = _scan_articles(
        ['israel_lebanon'],
        ['buffer zone', 'security zone', 'buffer', 'withdrawal', 'pullback', 'remains in']
    )
    qassem_military = _scan_articles(
        ['hezbollah_political'],
        ['qassem warns', 'qassem threatens', 'qassem military', 'resistance ready',
         'we will respond', 'resistance will not', 'open front']
    )
    shia_dissent = _scan_articles(
        ['lebanese_government'],
        ['shia protest', 'shia dissent', 'shia against hezbollah', 'sent to die',
         'hezbollah sacrifice', 'civilians against', 'lebanese against hezbollah',
         'radwan surrender', 'fighters surrender']
    )
    laf_active = _scan_articles(
        ['lebanese_government'],
        ['laf deploys south', 'army deploys litani', 'lebanese army south',
         'aoun orders', 'laf enforces', 'army arrests hezbollah']
    )
    idf_ultimatum = _scan_articles(
        ['israel_lebanon'],
        ['ultimatum', 'final warning', 'israel warns beirut', 'israel tells lebanon',
         'katz warns', 'deadline lebanon', 'israel demands']
    )
    unifil_withdraw = _scan_articles(
        ['unifil'],
        ['withdraw', 'evacuation', 'pull out', 'leave lebanon', 'unsafe',
         'unifil leaving', 'peacekeepers withdraw']
    )

    triggered = []

    # ── Hezbollah military re-activation ──
    if hezb_mil_level >= 3 or rockets >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hezbollah_military_reactivation'),
            'status':  'BREACHED' if (hezb_mil_level >= 4 or rockets >= 4) else 'APPROACHING',
            'trigger': f'Hezbollah military L{hezb_mil_level}, rockets L{rockets} -- Islamic Resistance operational signals',
        })

    # ── Litani violation ──
    if litani_signal or ground_ops >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'litani_violation'),
            'status':  'BREACHED' if (ground_ops >= 4 or litani_signal) else 'APPROACHING',
            'trigger': f'Litani River language detected + ground ops L{ground_ops} -- core Israeli red line',
        })

    # ── Iran weapons resupply ──
    if resupply_signal and iran_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'iran_weapons_resupply'),
            'status':  'APPROACHING',
            'trigger': f'Weapons transfer/resupply language detected + Iran coordination L{iran_level}',
        })

    # ── IDF buffer zone expansion ──
    if buffer_zone_signal and israel_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'idf_buffer_zone_expansion'),
            'status':  'APPROACHING',
            'trigger': f'Buffer zone/withdrawal language + Israel L{israel_level} -- IDF southern Lebanon posture',
        })

    # ── Qassem military authorization ──
    if qassem_military and hezb_pol_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'qassem_military_authorization'),
            'status':  'APPROACHING',
            'trigger': 'Qassem shifting to military authorization language -- political to operational signal',
        })

    # ── LAF enforcement failure ──
    if laf_level <= 1 and (hezb_mil_level >= 2 or ground_ops >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'laf_enforcement_failure'),
            'status':  'APPROACHING',
            'trigger': f'LAF L{laf_level} (minimal) while Hezbollah military L{hezb_mil_level} -- enforcement gap persists',
        })

    # ── UNIFIL withdrawal ──
    if unifil_withdraw or unifil_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'unifil_withdrawal'),
            'status':  'BREACHED' if unifil_level >= 4 else 'APPROACHING',
            'trigger': f'UNIFIL withdrawal language detected -- buffer removal signal',
        })

    # ── IDF ultimatum to GOL ──
    if idf_ultimatum:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'idf_ultimatum_gol'),
            'status':  'BREACHED',
            'trigger': 'IDF/Israel issuing direct ultimatum to Lebanese government -- forces response',
        })

    # ── Shia public dissent (de-escalation / Hezbollah legitimacy signal) ──
    if shia_dissent:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'shia_public_dissent'),
            'status':  'APPROACHING',
            'trigger': 'Lebanese Shia community distancing from Hezbollah -- legitimacy erosion signal',
        })

    # ── LAF active enforcement (positive signal) ──
    if laf_active:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'laf_enforces_south'),
            'status':  'APPROACHING',
            'trigger': 'LAF actively deploying/enforcing south Lebanon -- Israeli withdrawal condition signal',
        })

    triggered.sort(key=lambda x: (
        0 if x['status'] == 'BREACHED' else 1,
        -x['severity'],
        0 if x['category'] != 'deescalation_signal' else 1
    ))
    return triggered


def _match_historical(scan_data):
    """Match Lebanon signal state against historical precedents."""
    actors = scan_data.get('actors', {})

    hezb_mil_level = actors.get('hezbollah_military',  {}).get('escalation_level', 0)
    israel_level   = actors.get('israel_lebanon',      {}).get('escalation_level', 0)
    iran_level     = actors.get('iran_lebanon',        {}).get('escalation_level', 0)
    laf_level      = actors.get('lebanese_government', {}).get('escalation_level', 0)
    unifil_level   = actors.get('unifil',              {}).get('escalation_level', 0)
    ground_ops     = scan_data.get('ground_ops_level', 0)
    rockets        = scan_data.get('rockets_level',    0)

    iran_coord = iran_level >= 2
    laf_enforce = laf_level >= 3
    unifil_present = unifil_level >= 1

    matches = []

    for precedent in HISTORICAL_PRECEDENTS:
        sigs = precedent['signals']
        score = 0
        max_score = 0
        matched_signals = []
        missed_signals = []

        def check(condition, label, weight=1):
            nonlocal score, max_score
            max_score += weight
            if condition:
                score += weight
                matched_signals.append(label)
            else:
                missed_signals.append(label)

        if 'hezbollah_military_min' in sigs:
            check(hezb_mil_level >= sigs['hezbollah_military_min'],
                  f'Hezbollah military L{hezb_mil_level} >= L{sigs["hezbollah_military_min"]}', weight=3)

        if 'israel_level_min' in sigs:
            check(israel_level >= sigs['israel_level_min'],
                  f'Israel L{israel_level} >= L{sigs["israel_level_min"]}', weight=2)

        if 'iran_coordination' in sigs:
            check(iran_coord == sigs['iran_coordination'],
                  'Iran coordination active', weight=2)

        if 'laf_enforcement' in sigs:
            check(laf_enforce == sigs['laf_enforcement'],
                  f'LAF enforcement: {laf_enforce}', weight=1)

        if 'unifil_present' in sigs:
            check(unifil_present == sigs['unifil_present'],
                  'UNIFIL present', weight=1)

        if max_score == 0:
            continue

        similarity = round((score / max_score) * 100)
        if similarity >= 50:
            matches.append({
                'id':              precedent['id'],
                'label':           precedent['label'],
                'description':     precedent['description'],
                'source':          precedent['source'],
                'outcome':         precedent['outcome'],
                'window_hours':    precedent['window_hours'],
                'confidence':      precedent['confidence'],
                'similarity':      similarity,
                'matched_signals': matched_signals,
                'missed_signals':  missed_signals,
            })

    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]


def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Generate Lebanon command node assessment.
    Frame: Three-way analysis -- Hezbollah re-activation, IDF buffer,
    LAF/GOL conditions for Israeli withdrawal.
    """
    actors = scan_data.get('actors', {})

    hezb_pol_level  = actors.get('hezbollah_political', {}).get('escalation_level', 0)
    hezb_mil_level  = actors.get('hezbollah_military',  {}).get('escalation_level', 0)
    iran_level      = actors.get('iran_lebanon',        {}).get('escalation_level', 0)
    israel_level    = actors.get('israel_lebanon',      {}).get('escalation_level', 0)
    laf_level       = actors.get('lebanese_government', {}).get('escalation_level', 0)
    unifil_level    = actors.get('unifil',              {}).get('escalation_level', 0)

    ground_ops  = scan_data.get('ground_ops_level',  0)
    rockets     = scan_data.get('rockets_level',     0)
    ceasefire   = scan_data.get('ceasefire_level',   0)
    theatre_score = scan_data.get('rhetoric_score', scan_data.get('theatre_score', 0))
    delta = scan_data.get('delta', {}) or {}
    delta_dir = delta.get('direction', 'stable')
    score_change = delta.get('score_change', 0)

    breached_count = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    approaching_count = sum(1 for r in red_lines_triggered if r['status'] == 'APPROACHING')
    top_match = historical_matches[0] if historical_matches else None

    # Check for key signals
    laf_enforcement_gap = laf_level <= 1 and hezb_mil_level >= 2
    iran_directing = iran_level >= 2
    hezbollah_weakened = any(
        r['id'] in ('shia_public_dissent',) for r in red_lines_triggered
    )

    # ── Scenario label ──
    if hezb_mil_level >= 4 or rockets >= 4:
        scenario       = 'ACTIVE CONFLICT -- Hezbollah Resumed Operations'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif hezb_mil_level >= 3 or (iran_level >= 3 and ground_ops >= 2):
        scenario       = 'ELEVATED -- Hezbollah Re-Activation Signals'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif laf_enforcement_gap and israel_level >= 2:
        scenario       = 'WARNING -- LAF Enforcement Gap, IDF Buffer Holds'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    elif ceasefire >= 2 or laf_level >= 2:
        scenario       = 'MONITORING -- Diplomatic Activity, Conditions Uncertain'
        scenario_color = '#3b82f6'
        scenario_icon  = '🔵'
    else:
        scenario       = 'MONITORING -- Below Escalation Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation ──
    situation_parts = []

    if hezb_mil_level >= 2:
        situation_parts.append(
            f'Hezbollah military wing at L{hezb_mil_level} -- '
            f'{"resumed active operations on Iranian direction (March 2, 2026)" if hezb_mil_level >= 3 else "monitoring for re-activation signals"}. '
            f'Note: Hezbollah is operating in service of the Iranian axis, not in defense of Lebanon despite their framing.'
        )

    if iran_directing:
        situation_parts.append(
            f'Iran coordination active at L{iran_level} -- '
            f'Hezbollah is receiving direction from Tehran, not acting independently. '
            f'Radwan Force morale signals are degraded -- surrender reports indicate troops were sent to die by leadership.'
        )

    if israel_level >= 2:
        situation_parts.append(
            f'IDF posture re: Lebanon at L{israel_level} -- '
            f'Israel remains in south Lebanon buffer zone (Gaza yellow zone model). '
            f'Israeli withdrawal is conditioned on LAF enforcement of 1701 and Hezbollah disarmament south of Litani.'
        )

    if laf_enforcement_gap:
        situation_parts.append(
            f'LAF at L{laf_level} -- deployment without enforcement remains the 20-year pattern. '
            f'The critical question: what would GOL and LAF need to DO for Israel to feel confident enough to withdraw?'
        )

    if delta_dir == 'rising' and score_change >= 8:
        situation_parts.append(
            f'Score rising sharply (+{round(score_change)} from recent average) -- trajectory accelerating.'
        )

    # ── Key indicators ──
    indicators = []

    if laf_enforcement_gap:
        indicators.append(
            'LAF ENFORCEMENT GAP: Lebanese Armed Forces have not enforced 1701 in 20 years. '
            'Deployment south of Litani without active enforcement does not meet Israeli withdrawal conditions. '
            'Watch for: LAF arrests of Hezbollah members, confiscation of weapons, active patrols.'
        )

    if iran_directing:
        indicators.append(
            f'IRAN DIRECTION CONFIRMED: Hezbollah is not acting in Lebanese national interest -- '
            f'it entered the war March 2 on Iranian orders. This matters for Lebanese domestic politics: '
            f'Shia community is increasingly asking why Lebanon pays the price for Iranian strategy.'
        )

    if breached_count >= 1:
        indicators.append(
            f'{breached_count} red lines currently breached -- including signals that historically '
            f'precede Israeli military action in south Lebanon.'
        )

    if hezb_mil_level >= 2:
        indicators.append(
            'HEZBOLLAH RECONSTITUTION WATCH: Post-Nasrallah Hezbollah under Naim Qassem is weaker but '
            'still armed. Syria corridor resupply attempts are the key intelligence signal to watch. '
            'HTS now controls key Syria routes -- complicating but not eliminating Iranian resupply.'
        )

    # ── Assessment ──
    assessment_parts = []

    if top_match and top_match['similarity'] >= 60:
        assessment_parts.append(
            f'Current signal pattern shows {top_match["similarity"]}% similarity to '
            f'{top_match["label"]}. In that case: {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Confidence: {top_match["confidence"]}. '
            f'Historical response window: {top_match["window_hours"]}h. Analytical estimate only.'
        )
    else:
        if theatre_score >= 20:
            assessment_parts.append(
                'Signals present but below historical escalation threshold. '
                'Monitor LAF enforcement signals and Iran resupply attempts as leading indicators.'
            )

    # ── Watch list ──
    watch_items = [
        'LAF active enforcement south of Litani (arrests, weapons seizures) -- key Israeli withdrawal condition',
        'Iran/Syria corridor weapons transfer attempts -- Hezbollah reconstitution signal',
        'Qassem language shift from political to military framing -- operational authorization signal',
        'IDF northern command posture changes (buildup = preparation; drawdown = confidence in conditions)',
        'Lebanese Shia public opinion signals -- Hezbollah legitimacy erosion accelerating?',
    ]
    if unifil_level >= 2:
        watch_items.append('UNIFIL status -- any withdrawal signals remove buffer and complicate ceasefire architecture')

    return {
        'scenario':                scenario,
        'scenario_color':          scenario_color,
        'scenario_icon':           scenario_icon,
        'situation':               ' '.join(situation_parts),
        'key_indicators':          indicators,
        'assessment':              ' '.join(assessment_parts),
        'watch_list':              watch_items[:5],
        'laf_enforcement_gap':     laf_enforcement_gap,
        'iran_directing':          iran_directing,
        'generated_at':            datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Lebanon assessment generated from open-source signal data. '
            'Not a prediction. Verify through official channels. '
            'LAF enforcement gap and Iranian direction are analytical judgments based on documented patterns.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker.py with full scan_data.
    Returns interpretation dict added as result['interpretation'].
    """
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
        print(f'[Lebanon Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [],
            'interpreter_version': '1.0.0',
            'error':              str(e)[:200],
        }


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    test_data = {
        'rhetoric_score':  45,
        'ground_ops_level': 3,
        'rockets_level':    2,
        'ceasefire_level':  1,
        'crossborder_level': 2,
        'delta': {'direction': 'rising', 'score_change': 8},
        'actors': {
            'hezbollah_political': {'escalation_level': 2, 'statement_count': 8, 'top_articles': [
                {'title': 'Qassem warns resistance will respond to any Israeli aggression', 'published': ''},
            ]},
            'hezbollah_military': {'escalation_level': 3, 'statement_count': 15, 'top_articles': [
                {'title': 'Islamic Resistance fires rockets at northern Israel from south Lebanon', 'published': ''},
                {'title': 'Radwan forces engaged IDF south of Litani River', 'published': ''},
            ]},
            'iran_lebanon': {'escalation_level': 3, 'statement_count': 6, 'top_articles': [
                {'title': 'Iran directs Hezbollah to open Lebanese front in coordination with Gaza', 'published': ''},
            ]},
            'israel_lebanon': {'escalation_level': 3, 'statement_count': 12, 'top_articles': [
                {'title': 'IDF maintains buffer zone in south Lebanon, warns Hezbollah on Litani', 'published': ''},
                {'title': 'Katz warns Lebanon government to enforce 1701 or face consequences', 'published': ''},
            ]},
            'lebanese_government': {'escalation_level': 1, 'statement_count': 3, 'top_articles': [
                {'title': 'Lebanese army says it has deployed south but will not confront Hezbollah', 'published': ''},
            ]},
            'unifil': {'escalation_level': 1, 'statement_count': 2, 'top_articles': []},
            'france': {'escalation_level': 1, 'statement_count': 2, 'top_articles': []},
            'cyprus': {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'syria_border': {'escalation_level': 1, 'statement_count': 3, 'top_articles': [
                {'title': 'IDF strikes weapons convoy on Syria-Lebanon border', 'published': ''},
            ]},
        },
    }

    result = interpret_signals(test_data)

    print('\n' + '='*65)
    print('SCENARIO:', result['so_what']['scenario'])
    print('LAF ENFORCEMENT GAP:', result['so_what'].get('laf_enforcement_gap'))
    print('IRAN DIRECTING:', result['so_what'].get('iran_directing'))
    print('='*65)
    print('\nSITUATION:')
    print(result['so_what']['situation'][:400])
    print('\nKEY INDICATORS:')
    for ind in result['so_what']['key_indicators']:
        print(f'  -- {ind[:100]}')
    print('\nWATCH LIST:')
    for item in result['so_what']['watch_list']:
        print(f'  -> {item}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]}) [{rl["category"]}]')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]} | Window: {hm["window_hours"]}h')
