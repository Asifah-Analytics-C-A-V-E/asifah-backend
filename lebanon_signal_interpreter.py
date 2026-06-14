"""
lebanon_signal_interpreter.py
Asifah Analytics -- ME Backend Module
v1.1.0

Signal interpretation engine for the Lebanon Rhetoric Tracker.

Lebanon's analytical frame is now FOUR-WAY (v1.1.0):

  1. Is Hezbollah re-activating under Iranian direction
     (not in defense of Lebanon -- in service of the axis)?
  2. Is Israel going to stay in southern Lebanon, expand,
     or can conditions be created for withdrawal?
  3. Will the LAF/GOL ever actually enforce 1701 and give
     Israel confidence to pull back?
  4. [NEW v1.1.0] Is there a genuine diplomatic off-ramp, and
     is Hezbollah escalating specifically to blow it up?

Key contextual factors baked in:
  - Hezbollah entered the war March 2, 2026 on Iran direction
  - Radwan forces surrendered -- morale signal, sent to die
  - IDF is in south Lebanon creating a buffer zone (Gaza yellow zone model)
  - LAF is largely toothless -- deployment vs. enforcement is different
  - Lebanese Shia public opinion is diverging from Hezbollah
  - Post-Nasrallah Hezbollah is weaker but still armed
  - Syria corridor for re-arming is now contested (post-Assad HTS control)
  - APRIL 2026: Direct Israel-Lebanon talks opened at State Dept --
    first direct contact without diplomatic relations. Hezbollah is
    escalating rockets and street pressure specifically to derail talks.
    This is the dual-track moment: active war + active diplomacy.

CHANGELOG:
  v1.1.0 (2026-04-10):
    - Added GREEN_LINES system (diplomatic off-ramp signals)
    - Added _score_green_lines() function
    - Added _score_diplomatic_track() -- 0-100 diplomatic momentum score
    - Added dual-track output to so_what: military_scenario + diplomatic_scenario
    - Added Hezbollah-disrupting-diplomacy detection
    - Updated interpret_signals() to surface diplomatic_track in output
    - Updated standalone test with diplomatic scenario

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS (escalation triggers)
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
# GREEN LINE DEFINITIONS (diplomatic off-ramp signals)
# NEW v1.1.0 -- mirrors RED_LINES structure but tracks
# de-escalation and diplomatic momentum.
# ============================================================
GREEN_LINES = [
    {
        'id':       'direct_israel_lebanon_talks',
        'label':    'Direct Israel-Lebanon Diplomatic Contact',
        'detail':   'Ambassador-level or higher direct contact between Israel and Lebanon -- '
                    'unprecedented given lack of diplomatic relations',
        'momentum': 3,   # Momentum 3 = high diplomatic significance
        'color':    '#10b981',
        'icon':     '🤝',
        'category': 'direct_contact',
        'source':   'April 2026: Ambassadors Leiter (Israel), Issa (US/Lebanon), Hamadeh (Lebanon) '
                    'phone call + State Dept meeting April 15 -- first direct contact without diplomatic relations',
    },
    {
        'id':       'us_broker_active',
        'label':    'US Actively Brokering Israel-Lebanon Framework',
        'detail':   'United States is actively mediating between Israel and Lebanon with named envoys, '
                    'specific dates, and a diplomatic venue',
        'momentum': 3,
        'color':    '#10b981',
        'icon':     '🇺🇸',
        'category': 'us_mediation',
        'source':   'Historical pattern: US active brokerage (named envoys + venue + timeline) '
                    'is the prerequisite for any Lebanon ceasefire framework',
    },
    {
        'id':       'ceasefire_framework_proposed',
        'label':    'Formal Ceasefire Framework Under Discussion',
        'detail':   'A specific ceasefire proposal with terms is on the table -- '
                    'beyond general calls for de-escalation',
        'momentum': 2,
        'color':    '#22c55e',
        'icon':     '📋',
        'category': 'framework',
        'source':   'Nov 2024 ceasefire precedent -- framework required named conditions '
                    '(LAF south of Litani, IDF withdrawal timeline, Hezbollah disarmament)',
    },
    {
        'id':       'hezbollah_signals_openness',
        'label':    'Hezbollah Political Wing Signals Openness to Deal',
        'detail':   'Hezbollah political leadership uses language suggesting willingness to '
                    'negotiate or accept conditions -- distinct from military posture',
        'momentum': 2,
        'color':    '#22c55e',
        'icon':     '🕊️',
        'category': 'hezbollah_political',
        'source':   'Pattern: Hezbollah political softening historically preceded ceasefire '
                    'acceptance (Nov 2024 model)',
    },
    {
        'id':       'international_guarantor_active',
        'label':    'International Guarantor Engaged (France/EU/UN)',
        'detail':   'A credible international guarantor is actively participating in '
                    'Lebanon ceasefire architecture -- providing political cover for deal',
        'momentum': 1,
        'color':    '#4ade80',
        'icon':     '🌐',
        'category': 'international',
        'source':   'France played guarantor role in Nov 2024; any credible guarantor '
                    'reduces risk of Israeli rejection of deal',
    },
    {
        'id':       'laf_signals_willingness',
        'label':    'LAF Signals Willingness to Enforce South Lebanon',
        'detail':   'Lebanese Armed Forces leadership publicly commits to enforcement '
                    '(not just deployment) south of Litani -- the key Israeli condition',
        'momentum': 2,
        'color':    '#22c55e',
        'icon':     '🎖️',
        'category': 'laf_signal',
        'source':   'Israeli withdrawal condition: LAF enforcement (not just presence) '
                    'is the stated condition for IDF pullback from buffer zone',
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

    if hezb_mil_level >= 3 or rockets >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hezbollah_military_reactivation'),
            'status':  'BREACHED' if (hezb_mil_level >= 4 or rockets >= 4) else 'APPROACHING',
            'trigger': f'Hezbollah military L{hezb_mil_level}, rockets L{rockets} -- Islamic Resistance operational signals',
        })

    if litani_signal or ground_ops >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'litani_violation'),
            'status':  'BREACHED' if (ground_ops >= 4 or litani_signal) else 'APPROACHING',
            'trigger': f'Litani River language detected + ground ops L{ground_ops} -- core Israeli red line',
        })

    if resupply_signal and iran_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'iran_weapons_resupply'),
            'status':  'APPROACHING',
            'trigger': f'Weapons transfer/resupply language detected + Iran coordination L{iran_level}',
        })

    if buffer_zone_signal and israel_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'idf_buffer_zone_expansion'),
            'status':  'APPROACHING',
            'trigger': f'Buffer zone/withdrawal language + Israel L{israel_level} -- IDF southern Lebanon posture',
        })

    if qassem_military and hezb_pol_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'qassem_military_authorization'),
            'status':  'APPROACHING',
            'trigger': 'Qassem shifting to military authorization language -- political to operational signal',
        })

    if laf_level <= 1 and (hezb_mil_level >= 2 or ground_ops >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'laf_enforcement_failure'),
            'status':  'APPROACHING',
            'trigger': f'LAF L{laf_level} (minimal) while Hezbollah military L{hezb_mil_level} -- enforcement gap persists',
        })

    if unifil_withdraw or unifil_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'unifil_withdrawal'),
            'status':  'BREACHED' if unifil_level >= 4 else 'APPROACHING',
            'trigger': f'UNIFIL withdrawal language detected -- buffer removal signal',
        })

    if idf_ultimatum:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'idf_ultimatum_gol'),
            'status':  'BREACHED',
            'trigger': 'IDF/Israel issuing direct ultimatum to Lebanese government -- forces response',
        })

    if shia_dissent:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'shia_public_dissent'),
            'status':  'APPROACHING',
            'trigger': 'Lebanese Shia community distancing from Hezbollah -- legitimacy erosion signal',
        })

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


def _score_green_lines(scan_data):
    """
    NEW v1.1.0 -- Evaluate Lebanon diplomatic off-ramp signals.
    Returns list of triggered green lines with status and trigger text.
    Mirrors _score_red_lines() structure exactly.
    """
    actors = scan_data.get('actors', {})
    ceasefire = scan_data.get('ceasefire_level', 0)
    hezb_pol_level = actors.get('hezbollah_political', {}).get('escalation_level', 0)
    laf_level      = actors.get('lebanese_government', {}).get('escalation_level', 0)

    def _scan_articles(actor_ids, keywords):
        for aid in actor_ids:
            for art in actors.get(aid, {}).get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw in title for kw in keywords):
                    return True
        return False

    # Direct Israel-Lebanon contact signals
    direct_talks = _scan_articles(
        ['lebanese_government', 'israel_lebanon'],
        ['direct talks', 'direct negotiations', 'direct contact', 'first contact',
         'phone call israel lebanon', 'leiter', 'michel issa', 'hamadeh',
         'state department lebanon', 'washington talks',
         'اتصال لبناني إسرائيلي', 'مفاوضات مباشرة', 'أول اتصال',
         'שיחות ישירות לבנון', 'מגעים ישירים']
    )

    # US active mediation
    us_broker = _scan_articles(
        ['lebanese_government', 'israel_lebanon'],
        ['us envoy', 'us mediates', 'us broker', 'state department',
         'american mediator', 'us brokered', 'washington meeting',
         'rubio lebanon', 'us ambassador lebanon',
         'الوسيط الأمريكي', 'واشنطن وساطة']
    )

    # Ceasefire framework being discussed
    framework_signal = _scan_articles(
        ['lebanese_government', 'israel_lebanon', 'france'],
        ['ceasefire framework', 'peace framework', 'deal framework',
         'withdrawal terms', 'agreement terms', 'conditions for ceasefire',
         'إطار وقف إطلاق النار', 'بنود الاتفاق']
    )

    # Hezbollah political openness (distinct from military posture)
    hezb_political_soft = _scan_articles(
        ['hezbollah_political'],
        ['hezbollah open to', 'hezbollah considers', 'qassem ceasefire',
         'political solution', 'hezbollah accepts', 'resistance ceasefire',
         'حزب الله يقبل', 'حزب الله منفتح']
    )

    # International guarantor engaged
    guarantor_signal = _scan_articles(
        ['france', 'unifil'],
        ['france guarantees', 'france guarantee', 'eu guarantees',
         'un guarantees', 'french guarantee', 'international guarantee',
         'guarantor', 'ضامن دولي', 'فرنسا ضامن']
    )

    # LAF signals willingness to enforce
    laf_willing = _scan_articles(
        ['lebanese_government'],
        ['laf will enforce', 'army will enforce', 'deploy south of litani',
         'enforce 1701', 'army enforce', 'aoun promises enforcement',
         'الجيش يطبق', 'تطبيق القرار 1701']
    )

    triggered = []

    # Direct talks -- highest momentum signal
    if direct_talks or ceasefire >= 4:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'direct_israel_lebanon_talks'),
            'status': 'ACTIVE' if direct_talks else 'SIGNALED',
            'trigger': 'Direct Israel-Lebanon ambassador contact detected -- '
                       'first direct talks without diplomatic relations (April 2026)',
        })

    # US active brokerage
    if us_broker or ceasefire >= 3:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'us_broker_active'),
            'status': 'ACTIVE' if us_broker else 'SIGNALED',
            'trigger': 'US active mediation signals detected -- named envoys and diplomatic venue',
        })

    # Ceasefire framework
    if framework_signal or ceasefire >= 4:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'ceasefire_framework_proposed'),
            'status': 'ACTIVE' if framework_signal else 'SIGNALED',
            'trigger': f'Ceasefire framework language detected (ceasefire L{ceasefire})',
        })

    # Hezbollah political softening
    if hezb_political_soft and hezb_pol_level <= 3:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'hezbollah_signals_openness'),
            'status': 'SIGNALED',
            'trigger': 'Hezbollah political wing using non-military language -- softening signal',
        })

    # International guarantor
    if guarantor_signal:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'international_guarantor_active'),
            'status': 'ACTIVE',
            'trigger': 'International guarantor (France/EU/UN) actively engaged in Lebanon framework',
        })

    # LAF willingness
    if laf_willing or laf_level >= 3:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'laf_signals_willingness'),
            'status': 'ACTIVE' if laf_willing else 'SIGNALED',
            'trigger': f'LAF signaling willingness to enforce south Lebanon (LAF L{laf_level})',
        })

    # Sort by momentum descending
    triggered.sort(key=lambda x: -x['momentum'])
    return triggered


def _score_diplomatic_track(scan_data, green_lines_triggered):
    """
    NEW v1.1.0 -- Compute a 0-100 diplomatic momentum score.
    Also detects whether Hezbollah is escalating to DISRUPT diplomacy.

    Returns dict with:
      - score: 0-100
      - scenario: label string
      - scenario_color: hex
      - hezbollah_disrupting: bool (key analytical signal)
      - active_count: number of ACTIVE green lines
    """
    actors = scan_data.get('actors', {})
    hezb_mil_level = actors.get('hezbollah_military', {}).get('escalation_level', 0)
    hezb_pol_level = actors.get('hezbollah_political', {}).get('escalation_level', 0)
    ceasefire = scan_data.get('ceasefire_level', 0)
    rockets    = scan_data.get('rockets_level', 0)

    active_lines   = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']
    signaled_lines = [g for g in green_lines_triggered if g['status'] == 'SIGNALED']

    # Momentum score: weighted sum of active and signaled green lines
    momentum = sum(g['momentum'] * 20 for g in active_lines)
    momentum += sum(g['momentum'] * 10 for g in signaled_lines)
    momentum += ceasefire * 5   # ceasefire vector adds context
    score = min(100, momentum)

    # Diplomatic scenario label
    if score >= 75:
        scenario       = 'BREAKTHROUGH — Direct Talks Active, Framework Possible'
        scenario_color = '#10b981'
    elif score >= 50:
        scenario       = 'ACTIVE NEGOTIATION — US Brokering, Momentum Building'
        scenario_color = '#22c55e'
    elif score >= 30:
        scenario       = 'DIPLOMATIC SIGNALS — Off-Ramp Visible, Not Yet Real'
        scenario_color = '#84cc16'
    elif score >= 15:
        scenario       = 'LOW MOMENTUM — Calls for Talks, No Framework'
        scenario_color = '#f59e0b'
    else:
        scenario       = 'NO DIPLOMATIC TRACK — Military Logic Dominates'
        scenario_color = '#6b7280'

    # KEY DETECTION: Is Hezbollah escalating TO DISRUPT active diplomacy?
    # This fires when military track is high AND diplomatic track is active --
    # the exact dual-track pattern of April 2026.
    hezbollah_disrupting = (
        len(active_lines) >= 1 and   # diplomacy is real
        hezb_mil_level >= 4 and       # Hezbollah militarily active
        rockets >= 3                   # active rocket fire
    )

    return {
        'score':               score,
        'scenario':            scenario,
        'scenario_color':      scenario_color,
        'hezbollah_disrupting': hezbollah_disrupting,
        'active_count':        len(active_lines),
        'signaled_count':      len(signaled_lines),
    }


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

    iran_coord     = iran_level >= 2
    laf_enforce    = laf_level >= 3
    unifil_present = unifil_level >= 1

    matches = []

    for precedent in HISTORICAL_PRECEDENTS:
        sigs = precedent['signals']
        score = 0
        max_score = 0
        matched_signals = []
        missed_signals  = []

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


def _build_so_what(scan_data, red_lines_triggered, historical_matches,
                   green_lines_triggered, diplomatic_track):
    """
    Generate Lebanon command node assessment.
    v1.1.0: Four-way analysis -- military, IDF buffer, LAF/GOL, + diplomatic track.
    """
    actors = scan_data.get('actors', {})

    hezb_pol_level  = actors.get('hezbollah_political', {}).get('escalation_level', 0)
    hezb_mil_level  = actors.get('hezbollah_military',  {}).get('escalation_level', 0)
    iran_level      = actors.get('iran_lebanon',        {}).get('escalation_level', 0)
    israel_level    = actors.get('israel_lebanon',      {}).get('escalation_level', 0)
    laf_level       = actors.get('lebanese_government', {}).get('escalation_level', 0)
    unifil_level    = actors.get('unifil',              {}).get('escalation_level', 0)

    ground_ops    = scan_data.get('ground_ops_level',  0)
    rockets       = scan_data.get('rockets_level',     0)
    ceasefire     = scan_data.get('ceasefire_level',   0)
    theatre_score = scan_data.get('rhetoric_score', scan_data.get('theatre_score', 0))
    delta         = scan_data.get('delta', {}) or {}
    delta_dir     = delta.get('direction', 'stable')
    score_change  = delta.get('score_change', 0)

    breached_count   = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    approaching_count = sum(1 for r in red_lines_triggered if r['status'] == 'APPROACHING')
    top_match        = historical_matches[0] if historical_matches else None

    laf_enforcement_gap   = laf_level <= 1 and hezb_mil_level >= 2
    iran_directing        = iran_level >= 2
    hezbollah_disrupting  = diplomatic_track.get('hezbollah_disrupting', False)
    diplomatic_score      = diplomatic_track.get('score', 0)

    # ── Military scenario label ──
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

    # NEW v1.1.0: Diplomatic track situation
    if diplomatic_score >= 30:
        dipl_scenario = diplomatic_track.get('scenario', '')
        situation_parts.append(
            f'DIPLOMATIC TRACK ACTIVE (score {diplomatic_score}/100): {dipl_scenario}. '
            f'{diplomatic_track.get("active_count", 0)} green line(s) confirmed active. '
            f'Direct Israel-Lebanon ambassador contact opened April 2026 -- '
            f'first direct talks without diplomatic relations. State Dept meeting April 15.'
        )

    if hezbollah_disrupting:
        situation_parts.append(
            'DUAL-TRACK ALERT: Hezbollah is escalating rockets and street pressure '
            'SIMULTANEOUSLY with the opening of direct Israel-Lebanon diplomatic talks. '
            'This is Hezbollah classic playbook -- escalate militarily to blow up diplomacy '
            'that threatens their relevance. The Arabic press is already framing this: '
            '"Hezbollah plays with street fire through provocative moves" as talks open. '
            'Watch whether Israel pauses or escalates in response to the talks. '
            'A pause would signal US pressure working; continued strikes signal Netanyahu '
            'is using talks as cover while continuing military pressure.'
        )

    if delta_dir == 'rising' and score_change >= 8:
        situation_parts.append(
            f'Score rising sharply (+{round(score_change)} from recent average) -- trajectory accelerating.'
        )

    # ── Key indicators ──
    indicators = []

    if hezbollah_disrupting:
        indicators.append(
            'HEZBOLLAH DISRUPTION PATTERN: Military escalation simultaneous with diplomatic opening '
            'is Hezbollah attempting to collapse talks before they gain momentum. '
            'The April 15 State Dept meeting is the immediate tripwire -- '
            'watch for Hezbollah major attack in the 48-72 hours before talks.'
        )

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
            f'{breached_count} red line(s) currently breached -- including signals that historically '
            f'precede Israeli military action in south Lebanon.'
        )

    if hezb_mil_level >= 2:
        indicators.append(
            'HEZBOLLAH RECONSTITUTION WATCH: Post-Nasrallah Hezbollah under Naim Qassem is weaker but '
            'still armed. Syria corridor resupply attempts are the key intelligence signal to watch. '
            'HTS now controls key Syria routes -- complicating but not eliminating Iranian resupply.'
        )

    if diplomatic_score >= 50:
        indicators.append(
            'DIPLOMATIC OFF-RAMP: Direct Israel-Lebanon talks represent the most significant '
            'de-escalation signal since the Nov 2024 ceasefire. '
            'Watch April 15 State Dept meeting for framework outline. '
            'Key Israeli conditions: LAF enforcement south of Litani, Hezbollah disarmament. '
            'Key Lebanese condition: full IDF withdrawal, no security zone.'
        )

    # ── Assessment ──
    assessment_parts = []

    if top_match and top_match['similarity'] >= 60:
        assessment_parts.append(
            f'Military pattern shows {top_match["similarity"]}% similarity to '
            f'{top_match["label"]}. In that case: {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Confidence: {top_match["confidence"]}. '
            f'Historical response window: {top_match["window_hours"]}h. Analytical estimate only.'
        )

    # NEW v1.1.0: Add diplomatic track to assessment when active
    if diplomatic_score >= 30:
        assessment_parts.append(
            f'However: the diplomatic track (score {diplomatic_score}/100) introduces a '
            f'genuine off-ramp that has no historical analog in prior Lebanon escalation cycles. '
            f'Direct Israel-Lebanon talks are unprecedented. '
            f'If a framework emerges from April 15 talks, the military logic could collapse rapidly. '
            f'If talks fail or IDF escalates before April 15, escalation logic dominates. '
            f'The 72-96 hours around the April 15 meeting are the highest-stakes window.'
        )

    # ── Watch list ──
    watch_items = []

    # Diplomatic items come FIRST when track is active
    if diplomatic_score >= 30:
        watch_items.append(
            'April 15 State Dept talks -- Leiter (Israel) / Issa (US) / Hamadeh (Lebanon): '
            'watch for framework outline on LAF enforcement, IDF withdrawal timeline, Hezbollah disarmament'
        )
        watch_items.append(
            'Hezbollah response to talks -- major attack before April 15 = disruption attempt; '
            'silence = possible Iranian pressure to let talks proceed'
        )

    watch_items += [
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
        'watch_list':              watch_items[:6],   # Allow 6 items when diplomatic track active
        'laf_enforcement_gap':     laf_enforcement_gap,
        'iran_directing':          iran_directing,
        'hezbollah_disrupting':    hezbollah_disrupting,
        'diplomatic_score':        diplomatic_score,
        'diplomatic_scenario':     diplomatic_track.get('scenario', ''),
        'diplomatic_scenario_color': diplomatic_track.get('scenario_color', '#6b7280'),
        'generated_at':            datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Lebanon assessment generated from open-source signal data. '
            'Not a prediction. Verify through official channels. '
            'LAF enforcement gap and Iranian direction are analytical judgments based on documented patterns. '
            'Diplomatic track scoring reflects open-source signals only -- '
            'track record of talks matters more than announcements.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

_CIVIL_WAR_PRECEDENTS = (
    "the 1975-1990 civil war (sectarian militias, parallel armed authority, "
    "state collapse along the Beirut Green Line)",
    "the May 2008 clashes (Hezbollah vs. government and Sunni factions, resolved "
    "only by the Doha Agreement)",
)

_CIVIL_WAR_DISCLAIMER = (
    "This is a CONVERGENCE indicator, NOT a prediction of civil war. It reports "
    "which internal-conflict precursors are present; the reader completes the inference."
)


def _score_civil_war_convergence(scan_data):
    """Lebanon Internal-Fracture / Civil War Pressure convergence read (Slice 2).

    Reads the internal_fracture rhetoric vector (the spine) together with three
    independent amplifier layers: active external-war spillover (displacement /
    sectarian blame pressure), the disarmament-conditioned ceasefire flashpoint
    (which forces a state-vs-Hezbollah confrontation), and state-authority
    weakness (LAF quiet while Hezbollah active = enforcement vacuum).

    Convergence = MULTIPLE independent layers co-moving, not one source echoing.
    Bands: Latent -> Elevated -> Acute -> Critical. Estimative, precedent-anchored.
    Rhetoric-grounded; IDP/humanitarian load + internal GDELT events fold in later.
    """
    fr = int(scan_data.get('internal_fracture_level', 0) or 0)      # the spine
    go = int(scan_data.get('ground_ops_level', 0) or 0)
    rk = int(scan_data.get('rockets_level', 0) or 0)
    cb = int(scan_data.get('crossborder_level', 0) or 0)
    cf = int(scan_data.get('ceasefire_level', 0) or 0)
    spillover = max(go, rk, cb)

    actors  = scan_data.get('actors', {}) or {}
    hez_mil = int(actors.get('hezbollah_military', {}).get('escalation_level', 0) or 0)
    laf_lvl = int(actors.get('lebanese_government', {}).get('escalation_level', 0) or 0)
    state_weak = (laf_lvl <= 1 and hez_mil >= 2)

    # Independent amplifier layers present this cycle
    layers = []
    if fr >= 2:        layers.append('internal_fracture')         # sectarian/militia rhetoric
    if spillover >= 4: layers.append('war_spillover')             # active external war
    if cf >= 3:        layers.append('disarmament_flashpoint')    # ceasefire forces confrontation
    if state_weak:     layers.append('state_authority_vacuum')    # enforcement gap
    amps = len([l for l in layers if l != 'internal_fracture'])

    # Band: internal_fracture is the spine; amplifier convergence escalates it.
    if fr >= 5 or (fr >= 4 and amps >= 2):
        band = 'Critical'
    elif fr >= 4 or (fr == 3 and amps >= 2):
        band = 'Acute'
    elif fr >= 2 or amps >= 2:
        band = 'Elevated'
    else:
        band = 'Latent'

    amp_phrases = {
        'war_spillover':          'active cross-border war driving displacement and sectarian blame',
        'disarmament_flashpoint': 'a disarmament-conditioned ceasefire forcing a state-vs-Hezbollah confrontation',
        'state_authority_vacuum': 'a state-authority vacuum (LAF unable to enforce against Hezbollah)',
    }
    active_amps = [amp_phrases[l] for l in layers if l in amp_phrases]
    amp_clause = ('; co-occurring with ' + '; '.join(active_amps)) if active_amps else ''

    if band == 'Latent':
        answer = 'Hypothetical murmurings: internal-fracture signals are isolated, not converging.'
        assessment = (
            'Internal-fracture signals read as background sectarian tension rather than a '
            'converging civil-war pattern this cycle. No broad non-Hezbollah remilitarization '
            'or state-vs-militia mobilization detected.'
        )
    elif band == 'Elevated':
        answer = 'Rising tension: communal friction present, short of the mobilization that precedes internal conflict.'
        assessment = (
            'Sectarian friction and vigilantism signals are present but not yet joined by broad '
            'non-Hezbollah remilitarization' + amp_clause + '. This is consistent with rising '
            'communal tension, short of the armed mobilization that preceded ' + _CIVIL_WAR_PRECEDENTS[1] + '.'
        )
    elif band == 'Acute':
        answer = 'Real push beginning: non-Hezbollah remilitarization and state-vs-militia signals are converging.'
        assessment = (
            'Non-Hezbollah remilitarization (e.g. Lebanese Forces / Druze / armed factions), calls '
            'to resist the state, and sectarian friction are converging' + amp_clause + '. This is '
            'consistent with the pre-conflict mobilization that preceded ' + _CIVIL_WAR_PRECEDENTS[0] + '.'
        )
    else:  # Critical
        answer = 'Actively being pushed toward internal conflict: multiple independent layers are converging.'
        assessment = (
            'Multiple independent layers -- armed mobilization, state-vs-militia confrontation' +
            amp_clause + ' -- are converging at a level consistent with pre-civil-war conditions. '
            'Both ' + _CIVIL_WAR_PRECEDENTS[0] + ' and ' + _CIVIL_WAR_PRECEDENTS[1] +
            ' followed a similar convergence of communal grievance, parallel armed authority, and state paralysis.'
        )

    return {
        'band':            band,                 # Latent / Elevated / Acute / Critical
        'level':           fr,                   # internal-fracture spine level (0-5)
        'active_layers':   layers,
        'amplifier_count': amps,
        'answer':          answer,               # one-line murmurings-vs-push read
        'assessment':      assessment,           # estimative, precedent-anchored
        'precedent':       list(_CIVIL_WAR_PRECEDENTS),
        'disclaimer':      _CIVIL_WAR_DISCLAIMER,
        'coverage':        'rhetoric-grounded; IDP/humanitarian load and internal GDELT events not yet folded in (Slice 2b)',
    }


def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker.py with full scan_data.
    Returns interpretation dict added as result['interpretation'].
    v1.1.0: Now includes green_lines and diplomatic_track in output.
    """
    try:
        red_lines    = _score_red_lines(scan_data)
        green_lines  = _score_green_lines(scan_data)
        diplomatic   = _score_diplomatic_track(scan_data, green_lines)
        historical   = _match_historical(scan_data)
        civil_war    = _score_civil_war_convergence(scan_data)
        so_what      = _build_so_what(scan_data, red_lines, historical,
                                      green_lines, diplomatic)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
        active_gl   = [g for g in green_lines if g['status'] == 'ACTIVE']

        return {
            'so_what':             so_what,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'green_lines': {
                'triggered':         green_lines,
                'active_count':      len(active_gl),
                'signaled_count':    len(green_lines) - len(active_gl),
                'diplomatic_score':  diplomatic['score'],
            },
            'diplomatic_track':    diplomatic,
            'historical_matches':  historical,
            'civil_war_convergence': civil_war,
            'interpreter_version': '1.1.0',
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Lebanon Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'green_lines':        {'triggered': [], 'active_count': 0, 'signaled_count': 0, 'diplomatic_score': 0},
            'diplomatic_track':   {'score': 0, 'scenario': 'Unknown', 'hezbollah_disrupting': False},
            'historical_matches': [],
            'civil_war_convergence': {'band': 'Latent', 'level': 0, 'active_layers': [],
                                      'amplifier_count': 0, 'answer': '', 'assessment': '',
                                      'precedent': [], 'disclaimer': '', 'coverage': ''},
            'interpreter_version': '1.1.0',
            'error':              str(e)[:200],
        }


# ============================================================
# CANONICAL SIGNAL EMITTER (v2.0)
# ============================================================
# Maps Lebanon's vectors -> canonical platform-wide signal categories
# consumed by me_regional_bluf.py and global_pressure_index.py.
#
# Categories used by Lebanon:
#   red_line_breached    (severity 3 red lines)
#   kinetic_pressure     (Hezbollah strikes/rockets at L4+)
#   theatre_high         (composite L4+ catch-all)
#   crosstheater_iran_lebanon  (Iran directing Hezbollah)
#   regime_fracture      (LAF enforcement gap, GOL paralysis)
#   silence_anomaly      (suspicious silence from key actor)
#   diplomatic_active    (ceasefire/negotiation track live)
#   red_line_breached    (Hezbollah disrupting diplomacy -- special flavor)
# ============================================================

LEBANON_FLAG = '\U0001f1f1\U0001f1e7'  # 🇱🇧

# Universal escalation labels (matches platform standard)
_LEB_ESC_LABELS = {
    0: 'Monitoring',
    1: 'Routine',
    2: 'Elevated Rhetoric',
    3: 'Heightened Posture',
    4: 'Active Signaling',
    5: 'Active Conflict',
}


def build_top_signals(scan_data):
    """
    Convert Lebanon scan_data into canonical top_signals[] for the regional BLUF
    and the Global Pressure Index. Schema:

        {
          'priority':   int 0-15 (higher == more urgent),
          'category':   str (canonical bucket),
          'theatre':    'lebanon',
          'level':      int 0-5,
          'icon':       str (emoji),
          'color':      str (hex),
          'short_text': str (<=80 char headline),
          'long_text':  str (<=200 char tooltip / detail),
        }

    Always returns a list (possibly empty). Sorted by priority desc.
    """
    signals = []

    interp        = scan_data.get('interpretation') or {}
    so_what       = interp.get('so_what') or {}
    rl_block      = interp.get('red_lines') or {}
    gl_block      = interp.get('green_lines') or {}
    dipl          = interp.get('diplomatic_track') or {}
    triggered_rls = rl_block.get('triggered') or []
    triggered_gls = gl_block.get('triggered') or []

    theatre_level   = int(scan_data.get('theatre_level', 0) or 0)
    theatre_score   = int(scan_data.get('rhetoric_score',
                          scan_data.get('theatre_score', 0)) or 0)
    rockets_level   = int(scan_data.get('rockets_level', 0) or 0)
    ground_ops_lvl  = int(scan_data.get('ground_ops_level', 0) or 0)

    # -- Turkey Levant-vector signal (Jun 11 2026): reads the Turkey
    # swing-state fingerprint. Reportable from the economic rung upward;
    # the security rung is the Libya-model tripwire.
    _tk_band  = str(scan_data.get('turkey_lebanon_vector', 'dormant'))
    _tk_stage = int(scan_data.get('turkey_lebanon_vector_stage', 0) or 0)
    if _tk_band in ('economic', 'security', 'kinetic_risk'):
        _tk_map = {'economic':    (8, 2, '💰'),
                   'security':    (11, 4, '⚔️'),
                   'kinetic_risk': (13, 5, '🚨')}
        _prio, _lvl, _icon = _tk_map[_tk_band]
        signals.append({
            'priority':   _prio,
            'category':   'crosstheater_turkey_lebanon',
            'theatre':    'lebanon',
            'level':      _lvl,
            'icon':       _icon,
            'color':      '#e11d48',
            'short_text': (f'🇱🇧 LEBANON: Turkey vector '
                           f'L{_tk_stage} ({_tk_band})'),
            'long_text':  (f'LEBANON: Turkey Levant-vector reads '
                           f'{_tk_band.replace("_", " ")} (stage L{_tk_stage}) on '
                           f'the documented playbook ladder. On the Libya-model '
                           f'precedent, security-cooperation class signals have '
                           f'historically preceded presence by invitation. '
                           f'Watch items: port concessions, defense MOU language, '
                           f'buffer-zone framing. Convergence read, not prediction.'),
        })
    crossborder_lvl = int(scan_data.get('crossborder_level', 0) or 0)
    ceasefire_lvl   = int(scan_data.get('ceasefire_level', 0) or 0)
    internal_fracture_lvl = int(scan_data.get('internal_fracture_level', 0) or 0)

    # ── Civil War Pressure convergence (Slice 2) -> BLUF / GPI ──
    cw = interp.get('civil_war_convergence') or {}
    if cw.get('band') in ('Elevated', 'Acute', 'Critical'):
        _cw_prio  = {'Elevated': 7, 'Acute': 10, 'Critical': 13}[cw['band']]
        _cw_color = {'Elevated': '#f59e0b', 'Acute': '#f97316', 'Critical': '#dc2626'}[cw['band']]
        signals.append({
            'priority':   _cw_prio,
            'category':   'civil_war_convergence',
            'theatre':    'lebanon',
            'level':      internal_fracture_lvl,
            'icon':       '🔥',
            'color':      _cw_color,
            'short_text': (f'🇱🇧 LEBANON: Civil-war pressure {cw["band"]} '
                           f'(internal fracture L{internal_fracture_lvl})'),
            'long_text':  ((cw.get('answer', '') + ' ' + cw.get('assessment', '') + ' '
                            + cw.get('disclaimer', '')).strip())[:480],
        })

    actors          = scan_data.get('actors') or {}
    silence_alerts  = scan_data.get('silence_anomalies') or []
    laf_gap         = bool(so_what.get('laf_enforcement_gap', False))
    iran_directing  = bool(so_what.get('iran_directing', False))
    hez_disrupting  = bool(dipl.get('hezbollah_disrupting',
                           so_what.get('hezbollah_disrupting', False)))

    # ── Color helpers ────────────────────────────────────────────────
    def lvl_color(lvl):
        return {0:'#6b7280', 1:'#16a34a', 2:'#facc15', 3:'#f59e0b',
                4:'#f97316', 5:'#dc2626'}.get(int(lvl), '#6b7280')

    # ── 1. Red lines BREACHED (severity 3) ───────────────────────────
    for rl in triggered_rls:
        if not isinstance(rl, dict):
            continue
        if rl.get('status') != 'BREACHED':
            continue
        sev   = int(rl.get('severity', 0) or 0)
        label = str(rl.get('label', 'Red line'))[:55]
        signals.append({
            'priority':   12 if sev >= 3 else 10,
            'category':   'red_line_breached',
            'theatre':    'lebanon',
            'level':      max(theatre_level, 4),
            'icon':       rl.get('icon', '🚨'),
            'color':      '#dc2626',
            'short_text': f'{LEBANON_FLAG} LEBANON: BREACH — {label}',
            'long_text':  (f'{LEBANON_FLAG} LEBANON red line breached: '
                           f'{rl.get("label", "")[:140]}'),
        })

    # ── 2. Hezbollah disrupting diplomacy (special breach flavor) ────
    if hez_disrupting and ceasefire_lvl >= 2:
        signals.append({
            'priority':   11,
            'category':   'red_line_breached',
            'theatre':    'lebanon',
            'level':      max(theatre_level, 4),
            'icon':       '🪓',
            'color':      '#dc2626',
            'short_text': (f'{LEBANON_FLAG} LEBANON: Hezbollah escalating to '
                           f'derail talks'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON dual-track: Hezbollah escalating '
                           f'kinetics specifically while diplomatic channel L'
                           f'{ceasefire_lvl} active. Spoiler dynamic.'),
        })

    # ── 3. Kinetic pressure — Hezbollah strikes / rockets L4+ ────────
    kinetic_lvl = max(rockets_level, ground_ops_lvl, crossborder_lvl)
    if kinetic_lvl >= 4:
        # Identify the most active vector
        if rockets_level >= max(ground_ops_lvl, crossborder_lvl):
            vec_name = 'rocket fire'
        elif ground_ops_lvl >= crossborder_lvl:
            vec_name = 'ground operations'
        else:
            vec_name = 'cross-border activity'
        signals.append({
            'priority':   9 + kinetic_lvl,   # L4=13, L5=14
            'category':   'kinetic_pressure',
            'theatre':    'lebanon',
            'level':      kinetic_lvl,
            'icon':       '🚀' if rockets_level == kinetic_lvl else '⚔️',
            'color':      lvl_color(kinetic_lvl),
            'short_text': (f'{LEBANON_FLAG} LEBANON: Active {vec_name} '
                           f'L{kinetic_lvl}'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON kinetic vector at L{kinetic_lvl} '
                           f'({_LEB_ESC_LABELS.get(kinetic_lvl, "")}). '
                           f'Rockets L{rockets_level}, ground L{ground_ops_lvl}, '
                           f'cross-border L{crossborder_lvl}.'),
        })

    # ── 4. Cross-theater: Iran directing Hezbollah ───────────────────
    if iran_directing:
        iran_actor = actors.get('iran_lebanon') or {}
        iran_lvl   = int(iran_actor.get('escalation_level',
                          iran_actor.get('max_escalation_level', 0)) or 0)
        signals.append({
            'priority':   10,
            'category':   'crosstheater_iran_lebanon',
            'theatre':    'lebanon',
            'level':      max(iran_lvl, 3),
            'icon':       '🕌',
            'color':      '#7c3aed',
            'short_text': (f'{LEBANON_FLAG} LEBANON: Iran directing Hezbollah '
                           f'reactivation'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON Iran-Hezbollah axis active — '
                           f'IRGC direction signals detected. Hezbollah operating '
                           f'in service of axis, not Lebanese national interest.'),
        })

    # ── 5. Theatre composite high (catch-all) ────────────────────────
    if theatre_level >= 4 or theatre_score >= 70:
        signals.append({
            'priority':   9,
            'category':   'theatre_high',
            'theatre':    'lebanon',
            'level':      theatre_level,
            'icon':       '🔴' if theatre_level >= 4 else '🟠',
            'color':      lvl_color(theatre_level),
            'short_text': (f'{LEBANON_FLAG} LEBANON L{theatre_level} — '
                           f'{_LEB_ESC_LABELS.get(theatre_level, "")}'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON at L{theatre_level} '
                           f'{_LEB_ESC_LABELS.get(theatre_level, "")} '
                           f'(score {theatre_score}/100).'),
        })

    # ── 6. Regime fracture: LAF enforcement gap ──────────────────────
    if laf_gap:
        signals.append({
            'priority':   9,
            'category':   'regime_fracture',
            'theatre':    'lebanon',
            'level':      max(theatre_level - 1, 3),
            'icon':       '🪖',
            'color':      '#f97316',
            'short_text': (f'{LEBANON_FLAG} LEBANON: LAF (Lebanese Armed Forces) '
                           f'enforcement gap'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON LAF cannot/will not enforce '
                           f'1701 disarmament. Deployment without enforcement -- '
                           f'Israel will not pull back without LAF teeth.'),
        })

    # ── 7. Silence anomalies (suspicious quiet from key actor) ───────
    for sa in silence_alerts[:2]:  # cap at 2 to avoid flooding
        if not isinstance(sa, dict):
            continue
        actor_id   = sa.get('actor_id', 'actor')
        actor_name = sa.get('actor_name', actor_id)
        signals.append({
            'priority':   9,
            'category':   'silence_anomaly',
            'theatre':    'lebanon',
            'level':      3,
            'icon':       '🔇',
            'color':      '#f59e0b',
            'short_text': (f'{LEBANON_FLAG} LEBANON: Silence anomaly — '
                           f'{actor_name[:35]}'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON unusual silence from '
                           f'{actor_name}. Could indicate operational planning, '
                           f'internal crisis, or message coordination.'),
        })

    # ── 8. Diplomatic active (ceasefire / negotiation track) ─────────
    if ceasefire_lvl >= 2:
        dipl_score = int(dipl.get('score', 0) or 0)
        dipl_scen  = str(so_what.get('diplomatic_scenario', dipl.get('scenario', ''))
                         or '')[:60]
        # Higher priority when score is climbing — this is a real off-ramp
        prio = 6 + min(ceasefire_lvl, 3)   # L2=8, L3=9, L4=9, L5=9
        signals.append({
            'priority':   prio,
            'category':   'diplomatic_active',
            'theatre':    'lebanon',
            'level':      ceasefire_lvl,
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': (f'{LEBANON_FLAG} LEBANON: Diplomatic track L'
                           f'{ceasefire_lvl} ({dipl_score}/100)'),
            'long_text':  (f'{LEBANON_FLAG} LEBANON diplomatic momentum '
                           f'L{ceasefire_lvl} -- {dipl_scen or "negotiation channel active"}. '
                           f'Modifier: {scan_data.get("diplomatic_modifier", 0)} pts.'),
        })

    # ── Sort and return ──────────────────────────────────────────────
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    # Test with April 2026 dual-track scenario
    test_data = {
        'rhetoric_score':    76,
        'ground_ops_level':  1,
        'rockets_level':     5,
        'ceasefire_level':   3,
        'crossborder_level': 1,
        'delta': {'direction': 'stable', 'score_change': 2},
        'actors': {
            'hezbollah_political': {'escalation_level': 5, 'statement_count': 88, 'top_articles': [
                {'title': 'أول اتصال لبناني إسرائيلي يمهد لإطلاق المفاوضات حزب الله يلعب بنار الشارع عبر تحركات استفزازية', 'published': ''},
                {'title': 'Hezbollah fires rockets at Kiryat Shmona as Lebanon Israel talks announced', 'published': ''},
            ]},
            'hezbollah_military': {'escalation_level': 5, 'statement_count': 131, 'top_articles': [
                {'title': 'Islamic Resistance fires rocket barrage at Kiryat Shmona settlement statement 58', 'published': ''},
                {'title': 'Hezbollah drones target Israeli barracks in northern Israel', 'published': ''},
            ]},
            'iran_lebanon': {'escalation_level': 1, 'statement_count': 1, 'top_articles': []},
            'israel_lebanon': {'escalation_level': 1, 'statement_count': 18, 'top_articles': [
                {'title': 'Netanyahu authorizes direct talks with Lebanon at State Department', 'published': ''},
            ]},
            'lebanese_government': {'escalation_level': 1, 'statement_count': 299, 'top_articles': [
                {'title': 'اول اتصال لبناني إسرائيلي يمهد لإطلاق المفاوضات direct talks state department', 'published': ''},
                {'title': 'وقف النار في لبنان مفتاح المحادثات مع إسرائيل هل يبدأ التفاوض', 'published': ''},
                {'title': 'Hamadeh Leiter phone call paves way for Washington talks', 'published': ''},
            ]},
            'unifil': {'escalation_level': 1, 'statement_count': 1, 'top_articles': []},
            'france': {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'cyprus': {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'syria_border': {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
        },
    }

    result = interpret_signals(test_data)

    print('\n' + '='*70)
    print('MILITARY SCENARIO:', result['so_what']['scenario'])
    print('DIPLOMATIC SCENARIO:', result['so_what'].get('diplomatic_scenario', 'None'))
    print(f'DIPLOMATIC SCORE: {result["so_what"].get("diplomatic_score", 0)}/100')
    print(f'HEZBOLLAH DISRUPTING DIPLOMACY: {result["so_what"].get("hezbollah_disrupting", False)}')
    print('LAF ENFORCEMENT GAP:', result['so_what'].get('laf_enforcement_gap'))
    print('IRAN DIRECTING:', result['so_what'].get('iran_directing'))
    print('='*70)
    print('\nSITUATION:')
    print(result['so_what']['situation'][:600])
    print('\nKEY INDICATORS:')
    for ind in result['so_what']['key_indicators']:
        print(f'  -- {ind[:120]}')
    print('\nWATCH LIST:')
    for item in result['so_what']['watch_list']:
        print(f'  -> {item[:100]}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]})')
    print('\nGREEN LINES:')
    for gl in result['green_lines']['triggered']:
        print(f'  {gl["icon"]} [{gl["status"]}] {gl["label"]} (Momentum {gl["momentum"]})')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]} | Confidence: {hm["confidence"]}')
    print(f'\nDIPLOMATIC TRACK: score={result["diplomatic_track"]["score"]}, '
          f'active={result["diplomatic_track"]["active_count"]}, '
          f'disrupting={result["diplomatic_track"]["hezbollah_disrupting"]}')
