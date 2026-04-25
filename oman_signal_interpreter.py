"""
Asifah Analytics -- Oman Signal Interpreter
Red Lines + So What strategic scenario builder
v1.0 - April 2026

Oman has DUAL-AXIS scoring (threat_level + influence_level), so the scenario
matrix is more nuanced than threat-only trackers like Iran or Yemen.

SCENARIO MATRIX:

  Threat 0-2 + Influence 0-2  -> QUIET STABILITY
                                 Routine baseline. Sultan visible, no incoming threats,
                                 no major mediation in progress.

  Threat 0-2 + Influence 3-5  -> DIPLOMATIC HUB ACTIVE
                                 Oman is exercising soft power. Mediation channels
                                 active (US-Iran, Houthi releases, Hamas indirect).
                                 This is a STABILITY signal — not an alarm.

  Threat 3-4 + Influence 0-2  -> EXTERNAL THREAT EMERGENT
                                 Iran/Houthi targeting Salalah/Duqm, or Yemen border
                                 spillover, or Baloch unrest. Oman's strategic
                                 vulnerability surfaces are activating.

  Threat 3-4 + Influence 3-5  -> CRISIS MEDIATION
                                 Both threat AND mediation high — usually means
                                 Oman is brokering a high-stakes situation under
                                 active threat conditions. Historical: Mariel-style
                                 diplomatic emergency.

  Threat 5     + any          -> SUCCESSION CRISIS / KINETIC ATTACK
                                 Either Sultan health crisis confirmed, OR Iran has
                                 actually struck Salalah/Duqm (not just rhetoric).
                                 ME regional risk floor rises substantially.

RED LINES:
  - Sultan public absence > 7 days during scan window      (succession_watch L4+)
  - Iran rhetoric explicitly naming Salalah/Duqm as target (external L4+)
  - Confirmed kinetic attack on Omani territory            (external L5)
  - Mass arrests of Omani dissidents/activists            (security L4+)
  - Crown Prince Theyazin emergency elevation              (succession L4+)

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
"""


# ============================================
# RED LINES — High-priority signals that require
#             immediate analyst attention
# ============================================

def check_red_lines(result):
    """
    Returns list of red line dicts that have been BREACHED or are APPROACHING.
    Each red line includes: name, status (BREACHED/APPROACHING), description,
    and category (threat/influence/succession).
    """
    red_lines = []
    actors = result.get('actors', {})
    threat_level = result.get('threat_level', 0)
    influence_level = result.get('influence_level', 0)

    succession = actors.get('succession_watch', {}).get('escalation_level', 0)
    external   = actors.get('external_threats_inbound', {}).get('escalation_level', 0)
    security   = actors.get('omani_security', {}).get('escalation_level', 0)
    mediation  = actors.get('mediation_activity', {}).get('escalation_level', 0)

    # ── Succession red line ──
    if succession >= 4:
        red_lines.append({
            'name':        'Sultan Health / Succession Crisis',
            'status':      'BREACHED',
            'description': 'Sultan health/succession signals at L4+. Crown Prince Theyazin profile may be emergency-elevated. Watch Diwan and royal court output for confirmation.',
            'category':    'succession',
            'icon':        '👑',
        })
    elif succession == 3:
        red_lines.append({
            'name':        'Sultan Public Absence Pattern',
            'status':      'APPROACHING',
            'description': 'Succession-watch signals elevated to L3. Sultan absence patterns or heir profile movements warrant tracking.',
            'category':    'succession',
            'icon':        '👑',
        })

    # ── External threat red lines ──
    if external >= 5:
        red_lines.append({
            'name':        'Kinetic Attack on Omani Territory',
            'status':      'BREACHED',
            'description': 'External threat vector at L5 — confirmed strike, attack, or kinetic incident on Omani soil (Salalah, Duqm, Muscat, or Dhofar). ME regional risk floor rises.',
            'category':    'threat',
            'icon':        '💥',
        })
    elif external >= 4:
        red_lines.append({
            'name':        'Iran/Houthi Targeting Oman',
            'status':      'BREACHED',
            'description': 'Iran or Houthi rhetoric explicitly naming Salalah, Duqm, or Omani assets as targets. Cross-theater fingerprint from Iran tracker is firing.',
            'category':    'threat',
            'icon':        '🚨',
        })
    elif external == 3:
        red_lines.append({
            'name':        'External Threat Pressure Building',
            'status':      'APPROACHING',
            'description': 'External threat signals at L3. Yemen border, Salalah/Duqm references, or Baloch spillover concerns rising.',
            'category':    'threat',
            'icon':        '⚠️',
        })

    # ── Security suppression red line (atypical for Oman) ──
    if security >= 4:
        red_lines.append({
            'name':        'Internal Security Crackdown',
            'status':      'BREACHED',
            'description': 'Royal Oman Police / ISS suppression activity at L4+. This is atypical for Oman — represents major shift from baseline benign police-state posture.',
            'category':    'threat',
            'icon':        '🛡️',
        })

    # ── Mediation indicator (NOT a threat — informational red line) ──
    if mediation >= 4:
        red_lines.append({
            'name':        'High-Stakes Mediation Active',
            'status':      'INFORMATIONAL',
            'description': 'Oman channel is active at L4+ — likely brokering a major US-Iran, Israel-Iran, or Yemen ceasefire negotiation. Iran tracker should de-escalate as result.',
            'category':    'influence',
            'icon':        '🕊️',
        })

    return red_lines


# ============================================
# SO WHAT — Strategic scenario assessment
# ============================================

def build_so_what(result):
    """
    Returns a strategic assessment dict modeling Oman's current scenario.
    Includes scenario name, situation, assessment, watch_list, and scenario_color.
    """
    actors = result.get('actors', {})
    threat_level    = result.get('threat_level', 0)
    influence_level = result.get('influence_level', 0)

    succession = actors.get('succession_watch',          {}).get('escalation_level', 0)
    external   = actors.get('external_threats_inbound',  {}).get('escalation_level', 0)
    security   = actors.get('omani_security',            {}).get('escalation_level', 0)
    mediation  = actors.get('mediation_activity',        {}).get('escalation_level', 0)
    convening  = actors.get('regional_diplomatic_hub',   {}).get('escalation_level', 0)

    cross = result.get('cross_theater_signals', {})
    iran_command_level = cross.get('iran_command_node_level', 0)

    # ── Scenario selection ──

    # Catastrophic: Threat level 5 (kinetic attack OR succession crisis)
    if threat_level >= 5:
        if succession >= 5:
            scenario       = 'SUCCESSION CRISIS — Sultan Health Confirmed'
            scenario_color = '#7c2d12'
            scenario_icon  = '👑'
            situation      = (f"Sultan health vector at L{succession}. Open-source signals "
                              f"suggest dynastic transition is imminent or active. Crown "
                              f"Prince Theyazin bin Haitham succession architecture is "
                              f"being tested in real time.")
            assessment     = ("Oman's stability rests on Sultan continuity. A confirmed "
                              "succession event during active regional conflict (Iran war, "
                              "Yemen, Hormuz blockade) creates compound risk. ME regional "
                              "risk floor rises. Iran-US back-channel may pause until "
                              "transition is resolved.")
            watch_list = [
                'Theyazin bin Haitham public visibility',
                'Diwan official statements / silence patterns',
                'GCC member statements on Oman succession',
                'US embassy Muscat staff posture',
                'Asad bin Tariq mentions',
            ]
        else:
            scenario       = 'KINETIC ATTACK ON OMANI TERRITORY'
            scenario_color = '#dc2626'
            scenario_icon  = '💥'
            situation      = (f"External threat vector at L{external}. Confirmed kinetic "
                              f"event — Iran, Houthi, or non-state actor strike on Salalah, "
                              f"Duqm, Muscat, or Dhofar. This is unprecedented in Oman's "
                              f"modern history outside of brief 2022 limpet-mine incidents.")
            assessment     = ("ME regional risk floor rises substantially. UK and US "
                              "logistics in Indian Ocean compromised. Hormuz alternative "
                              "(Duqm) may be unavailable. Oman's strict neutrality posture "
                              "broken — likely to demand attribution and possibly retaliate "
                              "or seek security guarantees.")
            watch_list = [
                'Royal Oman Police statements on attribution',
                'US/UK military posture in Indian Ocean',
                'Sultan/MOFA statements on response',
                'Saudi/UAE Gulf solidarity messaging',
                'Iran tracker — denial vs. acknowledgment',
            ]

    # High threat (3-4) — external threat emerging
    elif threat_level >= 3:
        if external >= 3:
            scenario       = 'EXTERNAL THREAT EMERGENT — Salalah/Duqm Vulnerability'
            scenario_color = '#ea580c'
            scenario_icon  = '🚨'
            situation      = (f"External threat vector at L{external}. Iran or Houthi rhetoric "
                              f"is naming Omani territory or assets as targets. Yemen border "
                              f"or Baloch spillover may be activating.")
            if cross.get('iran_salalah_targeted'):
                situation += " Iran tracker confirms Salalah-targeting language detected."
            if cross.get('iran_duqm_logistics_active'):
                situation += " Iran tracker confirms Duqm UK-base rhetoric detected."
            assessment     = ("Oman has historically been spared kinetic targeting because "
                              "of its mediator role. Threat language naming Omani assets is "
                              "a significant deviation. Watch for whether Iran or Houthi "
                              "leadership backs off (testing red line) or escalates.")
            watch_list = [
                'Salalah container port operational status',
                'Duqm commercial shipping schedules',
                'US 5th Fleet posture in Gulf of Oman',
                'Houthi spokesperson named Oman targets',
                'Iran tracker — proxy direction signals',
            ]
        elif succession >= 3:
            scenario       = 'SUCCESSION WATCH — Health/Heir Signals Elevated'
            scenario_color = '#ea580c'
            scenario_icon  = '👑'
            situation      = (f"Succession-watch vector at L{succession}. Sultan public "
                              f"appearance patterns or Crown Prince profile movements "
                              f"warrant analyst attention.")
            assessment     = ("Open-source signals on Sultan health are weak by design — "
                              "Omani state media will not report illness. Watch absence "
                              "patterns, official decree volume, and royal court visibility "
                              "as indirect indicators. Crown Prince Theyazin profile "
                              "elevation is the cleanest forward indicator.")
            watch_list = [
                'Sultan public engagement frequency',
                'Crown Prince Theyazin appearances',
                'Royal Oman News Agency tone',
                'Diwan decree publication volume',
                'GCC peer outreach to Muscat',
            ]
        else:  # security elevated atypically
            scenario       = 'INTERNAL SECURITY ANOMALY'
            scenario_color = '#ea580c'
            scenario_icon  = '🛡️'
            situation      = (f"Security apparatus signals at L{security}. Atypical for "
                              f"Oman — represents shift from baseline benign police-state "
                              f"posture.")
            assessment     = ("Oman's internal security is normally invisible because the "
                              "regime maintains broad legitimacy. A visible spike usually "
                              "indicates either a specific dissident event, a security "
                              "scare (e.g., terror plot disrupted), or pre-emptive posture.")
            watch_list = [
                'Named arrests / activist detentions',
                'Salalah/Dhofar security checkpoints',
                'Social media platform restrictions',
                'Muscat protest activity',
            ]

    # Diplomatic hub active (low threat, high influence)
    elif influence_level >= 3:
        scenario       = 'DIPLOMATIC HUB ACTIVE — Oman Mediating'
        scenario_color = '#7c3aed'
        scenario_icon  = '🕊️'
        situation      = (f"Influence vector at L{influence_level}. Oman channel is active. "
                          f"Mediation activity at L{mediation}, regional convening at "
                          f"L{convening}.")
        if cross.get('iran_oman_diplomatic_active'):
            situation += " Iran tracker confirms Muscat back-channel is active."
        assessment     = ("This is a STABILITY signal, not an alarm. Oman exercising soft "
                          "power historically de-escalates regional tensions. The Iran "
                          "tracker should be reading oman:mediation_active as a downward "
                          "modifier on Iran-US conflict probability. Oman's value to "
                          "Washington and Tehran rises proportionally.")
        watch_list = [
            'Witkoff or US envoy visits to Muscat',
            'Iranian delegation arrivals',
            'Houthi hostage release announcements',
            'Hamas indirect contact signals',
            'GCC reaction to Oman channel',
        ]

    # Monitoring (low threat, low influence)
    elif threat_level >= 1 or influence_level >= 1:
        scenario       = 'MONITORING — Baseline Activity'
        scenario_color = '#0ea5e9'
        scenario_icon  = '🔵'
        situation      = (f"Threat L{threat_level}, Influence L{influence_level}. Routine "
                          f"signal activity above baseline noise.")
        assessment     = ("Oman in normal operational posture. Signals warrant continued "
                          "monitoring but no specific scenario has activated.")
        watch_list = [
            'Sultan Haitham visibility',
            'Salalah/Duqm port traffic',
            'GCC summit calendar',
            'Iran-US channel tempo',
            'Yemen border quiet',
        ]

    # Quiet baseline
    else:
        scenario       = 'QUIET STABILITY'
        scenario_color = '#16a34a'
        scenario_icon  = '🟢'
        situation      = ("Threat and influence vectors at baseline. Oman is in quiet "
                          "stable mode — no major signals, no kinetic concerns, no active "
                          "mediation visibility above noise.")
        assessment     = ("Oman's default state. The Sultanate's stability anchor function "
                          "is operating normally. Noteworthy mostly for what is NOT "
                          "happening — no Iran rhetoric naming Omani assets, no succession "
                          "anomalies, no mediation spikes.")
        watch_list = [
            'Sultan public engagement (continuity check)',
            'Salalah/Duqm operational tempo',
            'Iran tracker for cross-theater signals',
            'Yemen border quiet',
            'GCC routine diplomatic calendar',
        ]

    return {
        'scenario':         scenario,
        'scenario_color':   scenario_color,
        'scenario_icon':    scenario_icon,
        'situation':        situation,
        'assessment':       assessment,
        'watch_list':       watch_list,
        'threat_level':     threat_level,
        'influence_level':  influence_level,
        'confidence_note':  ('Analysis based on OSINT signal aggregation across English, '
                             'Arabic, Persian, and Hebrew sources. Open-source detection '
                             'of Sultan health is inherently weak — Omani state media will '
                             'not report illness. Asifah methodology should not be cited as '
                             'official assessment.'),
        'indicators':       [],
    }


# ============================================
# HISTORICAL MATCHES — Pattern recognition
# ============================================

def build_historical_matches(result):
    """
    Match current scan to historical Oman events. Returns list of historical analogs.
    """
    matches = []
    threat_level    = result.get('threat_level', 0)
    influence_level = result.get('influence_level', 0)
    actors          = result.get('actors', {})

    succession = actors.get('succession_watch',         {}).get('escalation_level', 0)
    external   = actors.get('external_threats_inbound', {}).get('escalation_level', 0)
    mediation  = actors.get('mediation_activity',       {}).get('escalation_level', 0)

    # 2020 Sultan Qaboos death
    if succession >= 4:
        matches.append({
            'year':       2020,
            'label':      'Sultan Qaboos Death (January 2020)',
            'similarity': ('Qaboos died after 50-year rule; sealed succession letter named '
                           'Haitham bin Tariq. Transition was fast and stable, but unique '
                           'to Qaboos\'s prepared architecture. Haitham has named Theyazin '
                           'as heir but uncertainty remains on actual transition mechanics.'),
            'score':      min(85, 50 + succession * 8),
        })

    # 2022 limpet mine attacks
    if external >= 4:
        matches.append({
            'year':       2022,
            'label':      'Gulf of Oman Tanker Attacks (May 2022)',
            'similarity': ('Limpet mines on tankers near Oman attributed to Iran. Oman '
                           'maintained neutrality posture but security concerns rose. '
                           'Salalah and Sohar port traffic temporarily impacted.'),
            'score':      min(75, 40 + external * 7),
        })

    # 2023-2024 Iran-US Muscat channel
    if mediation >= 3:
        matches.append({
            'year':       2024,
            'label':      'Muscat Round of Iran-US Indirect Talks (2023-2024)',
            'similarity': ('Witkoff and Iranian envoys met in Muscat as US-Iran tensions '
                           'mounted. Oman\'s neutral hosting role was central to keeping '
                           'channels open during crisis periods.'),
            'score':      min(80, 50 + mediation * 6),
        })

    # 2014 Houthi-Yemen mediation
    if mediation >= 3:
        matches.append({
            'year':       2015,
            'label':      'Oman Yemen Mediation (2014-2015)',
            'similarity': ('Oman was the only GCC state to maintain channels with both '
                           'Houthis and Saudi-led coalition during Yemen war. Brokered '
                           'multiple hostage releases throughout the conflict.'),
            'score':      min(70, 40 + mediation * 6),
        })

    return sorted(matches, key=lambda m: m['score'], reverse=True)[:3]
