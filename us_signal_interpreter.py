"""
========================================
U.S. SIGNAL INTERPRETER (v1.4.1 -- November 4, 2026 pm; v1.4.0 Nov 4 am; v1.3.0 Nov 1; v1.2.0 Sep 7 2026)
v1.4.1: So What bullets in plain words (PLAIN_GAP, ACTOR_PLAIN); the
        military bullet explains itself instead of printing scores.
v1.4.0: top-signal cards in plain words -- no "tripwires", no "[L4] vs capability net",
"x baseline" becomes "x their usual pace", the Fed card no longer ends in a question mark.
v1.3.0: stale facts removed from user-facing text (DHS 'funding constraints',
'v1.1 release' placeholder, Powell); Mojtaba Khamenei in Iran cadence terms.
========================================
Analytical layer for the US Rhetoric Tracker. Where the engine collects raw
signals, this module makes them MEAN something.

v1.1 ADDS: KINETIC-PRECURSOR CADENCE DETECTION
  Recognizes the structural pattern of US executive sequencing toward kinetic
  action against a foreign target. The Venezuela January 2026 raid was preceded
  by a 21-day cadence: intel disclosure → DOJ indictment → congressional warning
  → capability disclosure → "pretext" language. When the same cadence repeats
  against a new target (e.g., Cuba May 2026 — Ratcliffe Havana visit, Castro
  indictment, Hegseth congressional testimony, 300 drones disclosure, "pretext
  for military action" language), it is the highest-confidence pre-kinetic
  indicator available via OSINT.

  CRITICAL: stays APOLITICAL. Detects the PATTERN, not political content.
  Same logic regardless of administration. Cadence detection is a tradecraft
  observation, not editorial judgment.

v1.2 ADDS: THE CAPABILITY-RHETORIC JOIN
  Signal 7 has always told a human to go cross-reference the military tracker
  by hand. That instruction is now code. The military tracker writes a SIGNED
  capability read to Redis; this module sets it against measured rhetoric
  intensity. Rhetoric without capability is posturing; rhetoric against
  FALLING capability is the gap.

EXPORTS (v1.2):
  compute_top_signals(actor_results, articles, cross_theater_fps, capability=None) -> list
  compute_so_what_factor(actor_results, composite, outbound_targets, capability=None) -> dict
  compute_capability_rhetoric_gap(actor_results, capability) -> dict           [NEW v1.2]
  compute_branch_divergence_score(actor_results) -> float
  compute_domestic_fracture_score(actor_results, articles) -> float
  compute_escalation_cadence_score(actor_results, articles, target) -> dict    [NEW v1.1]
  compute_kinetic_precursor_targets(actor_results, articles) -> list           [NEW v1.1]

DESIGN PHILOSOPHY:
  1. APOLITICAL FRAMING. Never editorialize about whose rhetoric is "correct" —
     report VOLATILITY and DIVERGENCE, not partisan judgment.
  2. SO WHAT. Every metric must answer "why does this matter for stability?"
     in plain language a Foreign Service Officer would write.
  3. CROSS-SPECTRUM TRANSPARENCY. Always note when our signals lean partisan
     and how we're balancing them.
  4. CONCRETE OVER ABSTRACT. "ICE raid in Atlanta sparked 4-hour standoff"
     is better than "civil unrest indicators elevated."
  5. [v1.1] STRUCTURAL PATTERN OVER POLITICAL CONTENT. Cadence detection
     observes WHAT executive branches do when sequencing toward kinetic
     action, regardless of WHO is in office or WHY they're doing it.
"""

from datetime import datetime, timezone


# ════════════════════════════════════════════════════════════════════
# CAPABILITY-RHETORIC GAP (v1.2) -- THE JOIN
# ════════════════════════════════════════════════════════════════════
# Signal 7 of this module has, since it was written, instructed a human to
# "cross-reference against the Asifah Military Tracker fingerprint for
# actual fleet/troop movements. Rhetoric without movement = posturing;
# rhetoric with movement = preparation."
#
# That instruction is now code.
#
# The military tracker writes military:{actor}:capability_direction to
# Redis every scan, carrying a SIGNED read of whether that actor's
# capability is being applied or spent. The rhetoric tracker reads it and
# sets it against measured rhetoric intensity. Neither sensor can see this
# on its own. That is the whole point.
#
#   RHETORIC   CAPABILITY   READ
#   high       rising       credible buildup
#   high       flat         declaratory / deterrence signaling
#   high       FALLING      THE GAP
#   low        rising       quiet preparation (the most serious cell)
#   low        flat         baseline
#   low        falling      retrenchment
#
# APOLITICAL, consistent with the rest of this module: it measures whether
# declared posture is matched by measured capability. It does not judge
# whether either is correct.
#
# ABSENCE-HONEST: when the military read is stale, thin, or missing, this
# says so and refuses to name a cell. A confident wrong cell is worse than
# an admitted gap in coverage.
# ════════════════════════════════════════════════════════════════════

# Rhetoric bands, on the 0-100 actor score.
RHETORIC_HIGH_THRESHOLD = 55
RHETORIC_MODERATE_THRESHOLD = 35

# Capability bands, on projection share = projection / (projection + loss).
# Deliberately NOT on net_score: net is in raw score points and is not
# comparable across actors or across weeks. Share is bounded 0-1.
CAPABILITY_RISING_SHARE = 0.58
CAPABILITY_FALLING_SHARE = 0.42

# Below these, the military read is too thin to assert a direction.
MIN_CLASSIFIED_SHARE = 0.30
MIN_DIRECTIONAL_SCORE = 20.0

# Beyond this the military scan is too old to set against today's rhetoric.
MAX_CAPABILITY_AGE_HOURS = 36.0

GAP_CELLS = {
    ('high', 'rising'): (
        'credible_buildup',
        'Credible buildup',
        'Declared posture is matched by measured capability moving into theater. '
        'Rhetoric and hulls are telling the same story.'),
    ('high', 'flat'): (
        'declaratory',
        'Declaratory / deterrence signaling',
        'Rhetoric is running hot while measured capability holds level. Consistent '
        'with deterrence signaling rather than preparation: the statements are doing '
        'the work the deployments are not.'),
    ('high', 'falling'): (
        'the_gap',
        'THE GAP: rhetoric rising, capability falling',
        'Declared posture is escalating while measured capability is being spent '
        'faster than it is replaced. Historically the least sustainable configuration: '
        'either the rhetoric moderates, the capability is reinforced, or the gap is '
        'tested by an adversary who can also read the ledger.'),
    ('moderate', 'rising'): (
        'quiet_preparation',
        'Quiet preparation',
        'Capability is moving into theater without matching declaratory escalation. '
        'The most serious cell in the matrix: preparation that is not being announced '
        'is preparation that is not meant to deter.'),
    ('low', 'rising'): (
        'quiet_preparation',
        'Quiet preparation',
        'Capability is moving into theater with rhetoric at baseline. The most serious '
        'cell in the matrix: preparation that is not being announced is preparation '
        'that is not meant to deter.'),
    ('moderate', 'flat'): (
        'baseline',
        'Baseline',
        'Rhetoric and capability are both at routine levels. No divergence to report.'),
    ('low', 'flat'): (
        'baseline',
        'Baseline',
        'Rhetoric and capability are both at routine levels. No divergence to report.'),
    ('moderate', 'falling'): (
        'retrenchment',
        'Retrenchment',
        'Capability is being spent while rhetoric stays moderate. Consistent with an '
        'unannounced drawdown, sustainment strain, or attrition being absorbed quietly.'),
    ('low', 'falling'): (
        'retrenchment',
        'Retrenchment',
        'Capability is declining with rhetoric at baseline. Consistent with an '
        'unannounced drawdown, sustainment strain, or attrition being absorbed quietly.'),
}


# v1.4.1 (Nov 4 2026): what each cell MEANS, in words a reader can use.
# The old bullet printed "Credible buildup -- rhetoric 79/100 [L5] against
# measured capability net +29.5 (66% projection share...)" -- true, and
# unreadable, and it sat under a "Stable" headline without explaining why
# both can be right (the composite is domestic; this is the military lane).
PLAIN_GAP = {
    'credible_buildup': ('Military: what Washington says and what it is moving line up. '
                         'Tough statements are matched by forces heading out ({share} of '
                         'tracked military moves are deployments, not drawdowns). Statements '
                         'backed by hardware are the ones adversaries take seriously.'),
    'declaratory':      ('Military: the statements are tougher than the deployments. Forces are '
                         'holding steady while the rhetoric runs hot -- the classic shape of '
                         'deterrence by words.'),
    'the_gap':          ('Military: the rhetoric is rising while measured forces are being used up '
                         'faster than they are replaced. That gap does not last: either the words '
                         'cool, reinforcements arrive, or someone tests it.'),
    'quiet_preparation': ('Military: forces are moving out without matching public statements. '
                          'Preparation that is not announced is not meant to deter -- the cell '
                          'that most deserves attention.'),
    'retrenchment':     ('Military: forces are being drawn down or worn down without any '
                         'announcement. Consistent with a quiet pullback or strain being absorbed.'),
}

ACTOR_PLAIN = {
    'us_executive': 'the White House', 'us_state_dept': 'the State Department',
    'us_defense': 'the Pentagon', 'us_congress_majority': 'the congressional majority',
    'us_congress_opposition': 'the congressional minority', 'us_judicial': 'the courts',
    'us_dhs_ice': 'immigration enforcement (DHS/ICE)', 'us_federal_reserve': 'the Federal Reserve',
    'us_states': 'state governments', 'us_civil_mobilization': 'civil-society groups',
}


def _rhetoric_band(score):
    if score >= RHETORIC_HIGH_THRESHOLD:
        return 'high'
    if score >= RHETORIC_MODERATE_THRESHOLD:
        return 'moderate'
    return 'low'


def _capability_age_hours(scanned_at):
    """Hours since the military scan that produced this read. None if undatable."""
    if not scanned_at:
        return None
    try:
        txt = str(scanned_at).replace('Z', '+00:00')
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def compute_capability_rhetoric_gap(actor_results, capability, rhetoric_actor='us_executive'):
    """Set measured rhetoric intensity against measured capability direction.

    actor_results   the rhetoric tracker's per-actor results
    capability      the military:us:capability_direction fingerprint, or None
    rhetoric_actor  which rhetoric actor carries the declaratory posture

    Returns a dict that ALWAYS has 'available' and 'assessment'. When the
    military read is missing, stale or thin, available is False and the
    assessment says which, so the absence is visible rather than silent.
    """
    ra = (actor_results or {}).get(rhetoric_actor, {}) or {}
    try:
        rhetoric_score = float(ra.get('actor_score') or 0)
    except (TypeError, ValueError):
        rhetoric_score = 0.0
    rhetoric_tier = ra.get('tier', 'L0')

    base = {
        'available': False,
        'rhetoric': {
            'actor': rhetoric_actor,
            'score': round(rhetoric_score, 1),
            'tier': rhetoric_tier,
            'band': _rhetoric_band(rhetoric_score),
        },
        'capability': None,
        'cell': None,
        'label': None,
        'confidence': 'none',
        'assessment': '',
    }

    if not isinstance(capability, dict) or not capability:
        base['reason'] = 'no_military_fingerprint'
        base['assessment'] = (
            'Military capability fingerprint not available. The rhetoric read stands '
            'alone and cannot be set against measured capability this period. This is '
            'a coverage gap, not a finding.')
        return base

    try:
        projection = float(capability.get('projection_score') or 0)
        loss = float(capability.get('loss_score') or 0)
        net = float(capability.get('net_score') or 0)
    except (TypeError, ValueError):
        projection = loss = net = 0.0

    denom = projection + loss
    share = (projection / denom) if denom else None
    try:
        classified_share = float(capability.get('classified_share') or 0)
    except (TypeError, ValueError):
        classified_share = 0.0
    age_hours = _capability_age_hours(capability.get('scanned_at'))

    cap_block = {
        'actor': capability.get('actor', 'us'),
        'net_score': round(net, 2),
        'projection_score': round(projection, 2),
        'loss_score': round(loss, 2),
        'projection_share': round(share, 3) if share is not None else None,
        'classified_share': round(classified_share, 3),
        'scanned_at': capability.get('scanned_at'),
        'age_hours': round(age_hours, 1) if age_hours is not None else None,
        'by_direction': capability.get('by_direction'),
    }
    base['capability'] = cap_block

    # ---- Refuse to assert a cell when the read cannot carry one ----
    if age_hours is not None and age_hours > MAX_CAPABILITY_AGE_HOURS:
        base['reason'] = 'military_read_stale'
        base['assessment'] = (
            f'Military capability read is {age_hours:.0f}h old (limit '
            f'{MAX_CAPABILITY_AGE_HOURS:.0f}h) and must not be set against '
            f'present-tense rhetoric. Force a military rescan to restore the join.')
        return base

    if denom < MIN_DIRECTIONAL_SCORE:
        base['reason'] = 'insufficient_directional_signal'
        base['assessment'] = (
            f'Only {denom:.1f} points of directional military signal this period '
            f'(minimum {MIN_DIRECTIONAL_SCORE:.0f}). Too thin to characterise capability '
            f'direction. Absence of a reading here is a coverage gap, not a finding.')
        return base

    if classified_share < MIN_CLASSIFIED_SHARE:
        base['reason'] = 'low_classification_coverage'
        base['assessment'] = (
            f'Only {classified_share:.0%} of military signals carried a direction '
            f'(minimum {MIN_CLASSIFIED_SHARE:.0%}). The capability read rests on too '
            f'little of the corpus to set against rhetoric. Reported for transparency, '
            f'not as a finding.')
        return base

    # ---- Both sensors are usable. Name the cell. ----
    if share >= CAPABILITY_RISING_SHARE:
        cap_band = 'rising'
    elif share <= CAPABILITY_FALLING_SHARE:
        cap_band = 'falling'
    else:
        cap_band = 'flat'

    rhet_band = base['rhetoric']['band']
    cell, label, narrative = GAP_CELLS.get(
        (rhet_band, cap_band),
        ('baseline', 'Baseline', 'No divergence to report.'))

    # Confidence is driven by how much of the military corpus was readable
    # and how far each band sits from its boundary.
    if classified_share >= 0.50 and (share <= 0.35 or share >= 0.65):
        confidence = 'high'
    elif classified_share >= 0.40:
        confidence = 'medium'
    else:
        confidence = 'low'

    assessment = (
        f"{label}. Rhetoric ({rhetoric_actor.replace('us_', '').replace('_', ' ')}) at "
        f"{rhetoric_score:.0f}/100 [{rhetoric_tier}], {rhet_band}. Measured capability: "
        f"projection {projection:.1f} against loss {loss:.1f} (net {net:+.1f}, "
        f"{share:.0%} projection share), reading {cap_band}. {narrative}")

    if confidence != 'high':
        assessment += (
            f" Confidence {confidence}: {classified_share:.0%} of military signals "
            f"carried a direction this scan.")

    base.update({
        'available': True,
        'reason': None,
        'capability_band': cap_band,
        'cell': cell,
        'label': label,
        'confidence': confidence,
        'assessment': assessment,
        'is_divergence': cell in ('the_gap', 'quiet_preparation'),
    })
    return base


# ════════════════════════════════════════════════════════════════════
# BRANCH DIVERGENCE SCORE
# ════════════════════════════════════════════════════════════════════

def compute_branch_divergence_score(actor_results):
    """
    Measures how much the three branches of US government are saying
    contradictory things. Higher = more institutional friction.

    Inputs: scores for executive, legislative (both wings), judicial.
    Calc:   max actor score in each branch - min actor score in each branch,
            adjusted by tripwire pressure.
    Range:  0-100
    """
    exec_score = actor_results.get('us_executive', {}).get('actor_score', 0)
    state_score = actor_results.get('us_state_dept', {}).get('actor_score', 0)
    defense_score = actor_results.get('us_defense', {}).get('actor_score', 0)
    cong_maj = actor_results.get('us_congress_majority', {}).get('actor_score', 0)
    cong_opp = actor_results.get('us_congress_opposition', {}).get('actor_score', 0)
    judicial = actor_results.get('us_judicial', {}).get('actor_score', 0)

    # Executive branch internal divergence (rare but meaningful)
    exec_branch_max = max(exec_score, state_score, defense_score)
    exec_branch_min = min(exec_score, state_score, defense_score)
    exec_internal = exec_branch_max - exec_branch_min

    # Legislative branch divergence (majority vs opposition)
    leg_divergence = abs(cong_maj - cong_opp)

    # Judicial vs executive divergence (the "court blocks EO" signal)
    # If judicial activity is high while executive is high, that's institutional
    # friction. If judicial is low while executive is high, it's quiet acceptance.
    jud_vs_exec = abs(judicial - exec_score) if judicial > 30 and exec_score > 30 else 0

    # Weighted combination
    score = (exec_internal * 0.3 + leg_divergence * 0.4 + jud_vs_exec * 0.3)

    # Tripwire boost — if any branch had tripwires, friction is real
    total_tripwires = sum(actor_results.get(k, {}).get('tripwires', 0)
                           for k in ('us_executive', 'us_judicial', 'us_congress_opposition'))
    score += total_tripwires * 3

    return round(min(100, score), 1)


# ════════════════════════════════════════════════════════════════════
# DOMESTIC FRACTURE SCORE (cross-spectrum)
# ════════════════════════════════════════════════════════════════════

def compute_domestic_fracture_score(actor_results, articles):
    """
    Measures how internally divided US domestic rhetoric is. Distinct from
    branch divergence (which measures institutions) — this measures the
    LEFT/RIGHT/CENTER information environment.

    Inputs:
      - Reddit cross-spectrum subs (r/politics vs r/Conservative volume)
      - DHS/ICE rhetoric (high = polarizing topic active)
      - Congress majority vs opposition divergence
      - States vs federal rhetoric
    """
    # Layer 1: legislative divergence (already in branch_div but lensed differently)
    cong_maj = actor_results.get('us_congress_majority', {}).get('actor_score', 0)
    cong_opp = actor_results.get('us_congress_opposition', {}).get('actor_score', 0)
    leg_div = abs(cong_maj - cong_opp)

    # Layer 2: states vs federal
    states_score = actor_results.get('us_states', {}).get('actor_score', 0)
    fed_score = actor_results.get('us_executive', {}).get('actor_score', 0)
    state_fed_friction = abs(states_score - fed_score) if states_score > 25 and fed_score > 25 else 0

    # Layer 3: ICE/DHS as polarization indicator
    dhs_score = actor_results.get('us_dhs_ice', {}).get('actor_score', 0)
    ice_polarization = max(0, dhs_score - 25) * 0.6  # 25 baseline; above = polarizing

    # Layer 4: cross-spectrum article volume from Reddit
    reddit_left_count = 0
    reddit_right_count = 0
    reddit_center_count = 0
    for art in articles:
        if art.get('source_type') != 'reddit':
            continue
        sub = (art.get('source') or '').lower()
        if 'r/politics' in sub or 'r/liberal' in sub or 'r/democrats' in sub:
            reddit_left_count += 1
        elif 'r/conservative' in sub or 'r/republicans' in sub:
            reddit_right_count += 1
        elif 'r/moderatepolitics' in sub or 'r/centrist' in sub or 'r/neutralpolitics' in sub:
            reddit_center_count += 1

    total_partisan = reddit_left_count + reddit_right_count
    spectrum_imbalance = 0
    if total_partisan >= 10:
        ratio = max(reddit_left_count, reddit_right_count) / max(1, total_partisan)
        # Imbalanced = one side dominating discourse (high = fracture)
        spectrum_imbalance = (ratio - 0.5) * 80  # 0.5 = balanced, 1.0 = totally lopsided

    # Composite
    score = (leg_div * 0.3
             + state_fed_friction * 0.2
             + ice_polarization * 0.3
             + spectrum_imbalance * 0.2)

    return round(min(100, score), 1)


# ════════════════════════════════════════════════════════════════════
# TOP SIGNALS
# ════════════════════════════════════════════════════════════════════

def compute_top_signals(actor_results, articles, cross_theater_fps, capability=None):
    """
    Build the list of top signals to surface in the frontend's "Top Signals"
    card. Each signal has:
      short_text:  ≤80 char, wire-headline style
      long_text:   2-3 sentence "so what" explanation
      severity:    'low' | 'medium' | 'high' | 'critical'
      category:    domestic | foreign | institutional | civil_social | economic
      actor_key:   which actor surfaced this (for color coding)
    """
    signals = []

    # ── Signal 1: ICE/DHS rhetoric tempo ──
    dhs = actor_results.get('us_dhs_ice', {})
    dhs_score = dhs.get('actor_score', 0)
    dhs_count = dhs.get('statement_count', 0)
    dhs_trip = dhs.get('tripwires', 0)
    if dhs_score >= 40 or dhs_trip > 0:
        sev = 'high' if dhs_trip > 0 else ('medium' if dhs_score >= 50 else 'low')
        signals.append({
            'short_text': ("Immigration enforcement (ICE/DHS) in heavy coverage, with escalation language"
                           if dhs_trip > 0 else "Immigration enforcement (ICE/DHS) in heavy coverage"),
            'long_text': (
                f"{dhs_count} statements on immigration enforcement this scan"
                f"{' including escalation language' if dhs_trip > 0 else ''}. It is the most volatile "
                f"US domestic issue and a leading indicator for protests. Watch operational tempo and any "
                f"enforcement activity near polling, counting or certification sites."
            ),
            'severity': sev,
            'category': 'civil_social',
            'actor_key': 'us_dhs_ice',
        })
    elif dhs_score >= 25:
        signals.append({
            'short_text': "Immigration enforcement (ICE/DHS) coverage in its normal range",
            'long_text': (
                "Immigration enforcement signals in the normal range this period. During the "
                "election window, enforcement near polling or counting sites is tracked in the "
                "governance block."
            ),
            'severity': 'low',
            'category': 'civil_social',
            'actor_key': 'us_dhs_ice',
        })

    # ── Signal 2: Branch divergence ──
    exec_score = actor_results.get('us_executive', {}).get('actor_score', 0)
    judicial_score = actor_results.get('us_judicial', {}).get('actor_score', 0)
    if exec_score >= 50 and judicial_score >= 50:
        signals.append({
            'short_text': f"High executive + judicial activity -- institutional friction signal",
            'long_text': (
                f"Both executive ({exec_score}) and judicial ({judicial_score}) actors are running hot, "
                f"suggesting active court intervention on executive actions. This is institutional friction "
                f"working as designed -- a stability signal even if it FEELS volatile from inside DC."
            ),
            'severity': 'medium',
            'category': 'institutional',
            'actor_key': 'us_judicial',
        })

    # ── Signal 3: Trump executive tempo ──
    exec_data = actor_results.get('us_executive', {})
    exec_tier = exec_data.get('tier', 'L0')
    exec_trip = exec_data.get('tripwires', 0)
    if exec_data.get('baseline_ratio', 1.0) > 1.5:
        signals.append({
            'short_text': (f"White House statements running at {exec_data.get('baseline_ratio',1.0):.1f}x "
                           f"their usual pace"),
            'long_text': (
                f"The President, the White House and the cabinet are putting out statements at "
                f"{exec_data.get('baseline_ratio',1.0):.1f} times their usual pace"
                f"{', some with escalation language' if exec_trip else ''}. Pace is volume, not intent -- "
                f"an election week lifts it on its own -- so read what is being said in the "
                f"governance and foreign-policy signals."
            ),
            'severity': 'high' if exec_trip > 0 else 'medium',
            # v1.4.0: pace is VOLUME. It stays on the page but enters the GPI
            # governance axis only at L1 (context) unless escalation language hit.
            'level': 2 if exec_trip > 0 else 1,
            'category': 'domestic',
            'actor_key': 'us_executive',
        })

    # ── Signal 4: Foreign actor responses (cross-theater fingerprints) ──
    foreign_responses = []
    for theater, fp in (cross_theater_fps or {}).items():
        if not isinstance(fp, dict):
            continue
        # Look for indicators that this country is rhetoric-targeting US
        keys_to_check = ['us_targeted', 'targets_us', 'anti_us_active', 'us_pressure']
        for key in keys_to_check:
            if fp.get(key):
                foreign_responses.append(theater)
                break
    if len(foreign_responses) >= 3:
        signals.append({
            'short_text': f"{len(foreign_responses)} theaters showing US-targeted rhetoric",
            'long_text': (
                f"Multiple foreign actors ({', '.join(foreign_responses[:5])}) are running rhetoric "
                f"explicitly targeting the United States. This is a 'world responding to US posture' "
                f"signal — usually reactive, but worth noting when it crosses three or more theaters."
            ),
            'severity': 'medium' if len(foreign_responses) < 5 else 'high',
            'category': 'foreign',
            'actor_key': 'us_state_dept',
        })

    # ── Signal 5: State-federal friction ──
    states_score = actor_results.get('us_states', {}).get('actor_score', 0)
    if states_score >= 38:
        states_trip = actor_results.get('us_states', {}).get('tripwires', 0)
        signals.append({
            'short_text': f"State governors pushing back -- federalism rhetoric elevated",
            'long_text': (
                f"Governor-level pushback against federal posture is at L"
                f"{actor_results.get('us_states', {}).get('tier','L0')[1:]}. "
                f"Watch for: lawsuits filed by state AGs, sanctuary declarations, "
                f"national guard deployment disputes."
            ),
            'severity': 'high' if states_trip > 0 else 'medium',
            'category': 'institutional',
            'actor_key': 'us_states',
        })

    # ── Signal 6: Fed independence stress ──
    fed_score = actor_results.get('us_federal_reserve', {}).get('actor_score', 0)
    if fed_score >= 40:
        signals.append({
            'short_text': ("Pressure on the Federal Reserve's independence in the reporting"
                           if actor_results.get('us_federal_reserve', {}).get('tripwires', 0) else
                           "The Federal Reserve is in heavy coverage"),
            'long_text': (
                "Heavy reporting on the Fed. The causes differ in weight: a rate-decision week is routine; "
                "open friction between the White House and the Fed chair, or dissent inside the FOMC, is "
                "a signal for markets and for institutional independence. The headlines behind this "
                "card say which it is."
            ),
            'severity': 'medium' if actor_results.get('us_federal_reserve', {}).get('tripwires', 0) else 'low',
            'category': 'economic',
            'actor_key': 'us_federal_reserve',
        })

    # ── Signal 7: Defense / military posture ──
    defense_score = actor_results.get('us_defense', {}).get('actor_score', 0)
    defense_trip = actor_results.get('us_defense', {}).get('tripwires', 0)
    if defense_score >= 45 or defense_trip > 0:
        # v1.2: the cross-reference this signal used to ask a human to perform
        # is now performed here, when the military read is usable.
        _dod_gap = compute_capability_rhetoric_gap(actor_results, capability,
                                                   rhetoric_actor='us_defense')
        if _dod_gap.get('available'):
            _cap = _dod_gap['capability']
            _tail = (f"Measured military capability is reading "
                     f"{_dod_gap['capability_band']} "
                     f"(projection {_cap['projection_score']} against loss "
                     f"{_cap['loss_score']}, net {_cap['net_score']:+}). "
                     f"{_dod_gap['label']}.")
        else:
            _tail = (f"Military capability read unavailable this period "
                     f"({_dod_gap.get('reason', 'unknown')}), so rhetoric cannot be "
                     f"set against movement. Coverage gap, not a finding.")
        signals.append({
            'short_text': ("Pentagon rhetoric running hot, with escalation language" if defense_trip
                           else "Pentagon rhetoric running hot"),
            'long_text': (
                f"Pentagon / combatant command rhetoric running hot. "
                f"Rhetoric without movement is posturing; rhetoric with movement is "
                f"preparation. {_tail}"
            ),
            'severity': 'high' if defense_trip > 0 else 'medium',
            'category': 'foreign',
            'actor_key': 'us_defense',
        })

    # ── Signal: Capability-Rhetoric Gap (v1.2) -- THE JOIN ──
    # Two independent sensors disagreeing. Neither can see this alone.
    gap = compute_capability_rhetoric_gap(actor_results, capability)
    if gap.get('available'):
        _cell = gap['cell']
        if _cell == 'the_gap':
            _sev, _icon = 'critical', '🚨'
        elif _cell == 'quiet_preparation':
            _sev, _icon = 'critical', '🔇'
        elif _cell == 'credible_buildup':
            _sev, _icon = 'high', '⚓'
        elif _cell == 'declaratory':
            _sev, _icon = 'high', '📣'
        elif _cell == 'retrenchment':
            _sev, _icon = 'medium', '📉'
        else:
            _sev, _icon = 'low', '·'
        if _cell != 'baseline':
            _r = gap['rhetoric']
            _c = gap['capability']
            _plain = {
                'credible_buildup': 'US forces are moving in line with the tough talk (credible buildup)',
                'declaratory': 'US rhetoric is running ahead of force movements (deterrence signalling)',
                'the_gap': 'US rhetoric is rising while military capability is being spent',
                'quiet_preparation': 'US forces are moving without matching rhetoric (quiet preparation)',
                'retrenchment': 'US rhetoric and force posture are both pulling back',
            }.get(_cell, gap['label'])
            signals.append({
                'short_text': f"{_icon} {_plain}",
                'long_text': (gap['assessment'] + f" (Rhetoric reads {_r['score']:.0f}/100; the military "
                              f"tracker's projection-minus-losses balance is {_c['net_score']:+}.)"),
                'severity': _sev,
                'category': 'foreign',
                'actor_key': 'us_executive',
            })
    elif gap.get('reason') and gap['reason'] != 'no_military_fingerprint':
        # Absence-honest: a join we could not complete is worth saying out loud,
        # because silence would read as "no divergence".
        signals.append({
            'short_text': "Capability-rhetoric join unavailable this period",
            'long_text': gap['assessment'],
            'severity': 'low',
            'category': 'foreign',
            'actor_key': 'us_defense',
        })

    # ── Signal: Kinetic-Precursor Cadence (v1.1) ──
    # Structural detection of US executive sequencing toward foreign kinetic
    # action. APOLITICAL — pattern observation, not political content.
    cadence_targets = compute_kinetic_precursor_targets(actor_results, articles)
    for cdt in cadence_targets:
        if cdt['indicator_count'] >= 3:  # only surface 'forming' tier or higher
            tier = cdt['tier']
            if tier == 'pre_kinetic':
                sev = 'critical'
                short = f"🚨 PRE-KINETIC CADENCE: {cdt['flag']} {cdt['label']} -- 5/5 indicators (VZ 2026 pattern)"
            elif tier == 'developing':
                sev = 'high'
                short = f"⏱️ Cadence developing: {cdt['flag']} {cdt['label']} -- 4/5 indicators"
            else:
                sev = 'high'
                short = f"⏱️ Cadence forming: {cdt['flag']} {cdt['label']} -- 3/5 indicators"
            signals.append({
                'short_text': short,
                'long_text': cdt['assessment'],
                'severity': sev,
                'category': 'foreign',
                'actor_key': 'us_executive',
            })

    # ── Sort by severity ──
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    signals.sort(key=lambda s: severity_order.get(s.get('severity', 'low'), 9))

    return signals[:10]  # cap at 10


# ════════════════════════════════════════════════════════════════════
# SO WHAT FACTOR
# ════════════════════════════════════════════════════════════════════

def compute_so_what_factor(actor_results, composite, outbound_targets,
                           capability=None, articles=None):
    """
    Generate the headline "So What" framing for the dashboard. This is the
    elevator-pitch summary an FSO would write at the top of a daily brief.

    Returns dict with:
      factor:       short label
      description:  2-3 sentence narrative
      bullet_points: list of 3-5 strategic implications
    """
    _so_what_articles = articles

    # Determine the dominant story
    actors_by_score = sorted(actor_results.items(),
                             key=lambda kv: kv[1].get('actor_score', 0),
                             reverse=True)
    top_actor_key = actors_by_score[0][0] if actors_by_score else None
    top_actor_score = actors_by_score[0][1].get('actor_score', 0) if actors_by_score else 0

    # Calibration framing -- US is generally stable
    if composite < 26:
        factor = 'Quiet Week'
        description = (
            "U.S. rhetoric across all branches is at baseline. Coherent posture, low partisan "
            "divergence, allies aligned with messaging. The view from DC may feel quieter than "
            "usual; the view from the rest of the country is normalcy."
        )
    elif composite < 38:
        factor = 'Active / Stable'
        description = (
            "U.S. posture is assertive but coherent. Normal partisan disagreement is present "
            "but institutions are functioning. This is the median operating state -- not a "
            "stability concern even if individual statements draw headlines."
        )
    elif composite < 51:
        factor = 'Active+ / Watch'
        description = (
            "U.S. rhetoric tempo is elevated, trending toward volatile. Multiple branches are "
            "running hot simultaneously, which can indicate either a major foreign policy "
            "moment or escalating domestic friction. Worth daily monitoring."
        )
    elif composite < 66:
        factor = 'Volatile'
        description = (
            "Sharp partisan rhetoric divergence is present. Allies may be distancing themselves "
            "publicly; branches are issuing contradictory signals. From inside Washington this "
            "feels intense; broader country may not feel it equally outside political class."
        )
    elif composite < 76:
        factor = 'Volatile+ / Allied Friction'
        description = (
            "Branches are publicly contradicting each other, allies are showing public skepticism, "
            "and multiple foreign actors are responding directly to US posture. Real institutional "
            "friction. Worth elevated tracking and cross-theater correlation."
        )
    else:
        factor = 'Crisis Rhetoric'
        description = (
            "Branches are openly fighting in public, allies are breaking publicly, multiple foreign "
            "actors are targeting the US directly. This level is rare and indicates potential "
            "constitutional or international crisis. Cross-theater impact will be substantial."
        )

    # Build bullet points
    bullets = []

    # Bullet 0 (v1.2): the capability-rhetoric join leads when it has something
    # to say, because it is the only bullet no single sensor could produce.
    _gap = compute_capability_rhetoric_gap(actor_results, capability)
    if _gap.get('available') and _gap.get('cell') != 'baseline':
        _gc = _gap['capability']
        _plain = PLAIN_GAP.get(_gap.get('cell'))
        if _plain:
            _txt = _plain.format(share=f"{_gc.get('projection_share', 0):.0%}")
            if str(_gap.get('confidence', '')).lower() == 'low':
                _txt += ' (Low confidence: the military read is thin this cycle.)'
            bullets.append(_txt)
        else:
            bullets.append(f"{_gap['label']}. {_gap.get('assessment', '')}".strip())
    elif _gap.get('reason') and _gap['reason'] != 'no_military_fingerprint':
        bullets.append('Military: we could not set statements against force movements this '
                       'cycle (the military read is missing or too old).')

    # Bullet 1: ICE/DHS context (always relevant given calibration note)
    dhs = actor_results.get('us_dhs_ice', {})
    dhs_score = dhs.get('actor_score', 0)
    if dhs_score >= 38:
        bullets.append(
            "Immigration enforcement (DHS/ICE) is the most volatile domestic topic this period."
        )
    elif dhs.get('statement_count', 0) > 0:
        # v1.3.0: was "constrained by recent shutdown / DHS funding situation",
        # printed on every quiet scan including zero-data ones. A cause the
        # data does not show is not ours to state.
        bullets.append("DHS/ICE rhetoric in the normal range this period.")

    # Bullet 2: top actor
    if top_actor_key and top_actor_score > 30:
        actor_name = ACTOR_PLAIN.get(top_actor_key,
                                     top_actor_key.replace('us_', '').replace('_', ' '))
        bullets.append(f"Loudest voice this period: {actor_name} "
                       f"({round(top_actor_score)} out of 100).")

    # Bullet 3: outbound targets
    if outbound_targets:
        target_list = ', '.join([t['country'].title() for t in outbound_targets[:3]])
        bullets.append(f"Countries Washington is talking about most: {target_list}.")
    else:
        bullets.append("No specific country is being heavily rhetoric-targeted by US executive this period.")

    # Bullet 4: judicial signal
    jud_score = actor_results.get('us_judicial', {}).get('actor_score', 0)
    if jud_score >= 45:
        bullets.append(
            f"Judicial activity elevated ({jud_score}/100) -- institutional pushback "
            f"working as designed; this is healthy friction even if it feels disruptive."
        )

    # Bullet: Kinetic-precursor cadence (v1.1) -- structural observation
    # Apolitical: same logic regardless of administration.
    try:
        # v1.2 fix: this was passing an empty article list, so cadence could
        # never reach the So-What bullet no matter what the corpus contained.
        cadence_targets = compute_kinetic_precursor_targets(
            actor_results, _so_what_articles or [])
        elevated = [c for c in cadence_targets if c['indicator_count'] >= 3]
        if elevated:
            top = elevated[0]
            bullets.append(
                f"⏱️ Kinetic-precursor cadence active vs. {top['flag']} {top['label']} "
                f"({top['indicator_count']}/5 indicators, tier: {top['tier']}). Structural pattern "
                f"observation — same indicators repeat across administrations."
            )
    except Exception:
        pass  # cadence detection is additive; don't break so-what if it fails

    # Bullet 5: divergence framing
    if composite >= 51:
        bullets.append(
            "Cross-spectrum framing reminder: this score measures rhetoric VOLATILITY and "
            "DIVERGENCE, not aggression. Asifah is apolitical infrastructure."
        )

    return {
        'factor':         factor,
        'description':    description,
        'bullet_points':  bullets[:5],
        'composite_score': composite,
        'updated_at':     datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════════
# KINETIC-PRECURSOR CADENCE DETECTION (v1.1)
# ════════════════════════════════════════════════════════════════════
# Structural detection of US executive sequencing toward foreign kinetic
# action. APOLITICAL — same logic regardless of administration.
#
# The pattern (Venezuela January 2026 precedent, 21-day window):
#   1. INTEL_DISCLOSURE: senior intel official visits target country OR
#      public intelligence disclosure about target
#   2. LEGAL_PRETEXT:    DOJ indictment of target's senior officials
#   3. POLICY_PRETEXT:   Sec-Def or Sec-State congressional warning about target
#   4. CAPABILITY_DISCLOSURE: public reveal of target's kinetic capability
#      (drone arsenal, missile cache, etc.) that frames target as threat
#   5. ACTION_PRETEXT:   "pretext for military action" / "could become a
#      pretext" language from US official re: target
#
# Score = 20 points per indicator. 0-100 scale.
#   0-39:  baseline (some signals present, no cadence pattern)
#   40-59: cadence forming (3 indicators)
#   60-79: cadence developing (4 indicators)
#   80-100: cadence complete = pre-kinetic (5 indicators in 14-day window)

# Targets known to track for cadence (extensible)
_KINETIC_PRECURSOR_TARGETS = {
    'cuba': {
        'label': 'Cuba',
        'flag': '🇨🇺',
        'target_official_terms': ['castro', 'raul castro', 'diaz-canel', 'cuban government'],
        'intel_official_terms':  ['ratcliffe', 'cia director'],
        'intel_visit_locations': ['havana', 'cuba'],
        'capability_terms':      ['300 drones', 'drone threat', 'drone strike', 'mohajer cuba',
                                  'shahed cuba', 'iranian advisers cuba', 'iranian advisers havana',
                                  'cuban drone'],
    },
    'venezuela': {
        'label': 'Venezuela',
        'flag': '🇻🇪',
        'target_official_terms': ['maduro', 'venezuelan government'],
        'intel_official_terms':  ['ratcliffe', 'cia director'],
        'intel_visit_locations': ['caracas', 'venezuela'],
        'capability_terms':      ['mohajer venezuela', 'iranian engineers venezuela',
                                  'venezuela drone'],
    },
    'iran': {
        'label': 'Iran',
        'flag': '🇮🇷',
        'target_official_terms': ['khamenei', 'mojtaba', 'iranian government', 'irgc'],
        'intel_official_terms':  ['cia director iran', 'mossad iran'],
        'intel_visit_locations': ['tehran'],
        'capability_terms':      ['iran nuclear breakout', 'iran enrichment', 'iran missile cache'],
    },
}


def _detect_cadence_indicators(target_key, actor_results, articles):
    """
    Detect kinetic-precursor cadence indicators for a specific target.
    Returns dict with 5 boolean flags + count.

    APOLITICAL: pattern recognition only — no political framing of why.
    """
    target_cfg = _KINETIC_PRECURSOR_TARGETS.get(target_key, {})
    if not target_cfg:
        return {'count': 0, 'indicators': {}}

    target_terms     = target_cfg.get('target_official_terms', [])
    intel_terms      = target_cfg.get('intel_official_terms', [])
    visit_locations  = target_cfg.get('intel_visit_locations', [])
    capability_terms = target_cfg.get('capability_terms', [])

    indicators = {
        'intel_disclosure':       False,
        'legal_pretext':          False,
        'policy_pretext':         False,
        'capability_disclosure':  False,
        'action_pretext':         False,
    }

    # Aggregate text corpus: all article titles + actor matched-keyword strings
    corpus_parts = []
    for art in (articles or []):
        title = (art.get('title') or '').lower()
        desc  = (art.get('description') or art.get('snippet') or '').lower()
        corpus_parts.append(title + ' ' + desc)

    for actor_key in ('us_executive', 'us_state_dept', 'us_defense',
                       'us_congress_majority', 'us_congress_opposition',
                       'us_judicial', 'us_intelligence'):
        ac = actor_results.get(actor_key, {})
        kws = ac.get('keywords_matched', []) or []
        corpus_parts.append(' '.join(str(k).lower() for k in kws))
        # Also scan top_articles per actor
        for art in (ac.get('top_articles', []) or []):
            corpus_parts.append((art.get('title') or '').lower())

    corpus = ' '.join(corpus_parts)

    # ── INDICATOR 1: intel_disclosure ──
    # Senior intel official visits target country OR public intelligence disclosure
    for intel_term in intel_terms:
        if intel_term in corpus:
            for loc in visit_locations:
                if loc in corpus:
                    indicators['intel_disclosure'] = True
                    break
        if indicators['intel_disclosure']:
            break
    # Or generic intel disclosure framing
    if not indicators['intel_disclosure']:
        if any(phrase in corpus for phrase in (
            f'{target_key} intelligence disclosure',
            f'us intelligence {target_key}',
            f'cia warns {target_key}',
        )):
            indicators['intel_disclosure'] = True

    # ── INDICATOR 2: legal_pretext (DOJ indictment of target official) ──
    if 'indictment' in corpus or 'indicted' in corpus or 'doj charges' in corpus:
        for ot in target_terms:
            if ot in corpus:
                indicators['legal_pretext'] = True
                break

    # ── INDICATOR 3: policy_pretext (Sec-Def/State congressional warning) ──
    sec_terms = ['hegseth', 'secretary of defense', 'sec-def', 'rubio',
                 'secretary of state', 'sec-state']
    cong_terms = ['congressional hearing', 'congressional testimony',
                  'committee hearing', 'testified to congress',
                  'before congress', 'house committee', 'senate committee',
                  'diaz-balart']
    sec_active = any(t in corpus for t in sec_terms)
    cong_active = any(t in corpus for t in cong_terms)
    target_in_corpus = any(ot in corpus for ot in target_terms) or target_key in corpus
    if sec_active and cong_active and target_in_corpus:
        indicators['policy_pretext'] = True

    # ── INDICATOR 4: capability_disclosure ──
    for cap_term in capability_terms:
        if cap_term in corpus:
            indicators['capability_disclosure'] = True
            break

    # ── INDICATOR 5: action_pretext ──
    pretext_phrases = ['pretext for military action', 'pretext for action',
                       'could become a pretext', 'pretext for strike',
                       'military pretext', 'us military action against']
    for phrase in pretext_phrases:
        if phrase in corpus:
            # Verify target is in corpus too
            if target_in_corpus:
                indicators['action_pretext'] = True
                break

    count = sum(1 for v in indicators.values() if v)
    return {'count': count, 'indicators': indicators}


def compute_escalation_cadence_score(actor_results, articles, target='cuba'):
    """
    Compute kinetic-precursor cadence score for a specific foreign target.

    Returns dict with:
      target:           target country key
      label:            display name
      flag:             country flag emoji
      score:            0-100 (20 points per active indicator)
      tier:             'baseline' | 'forming' | 'developing' | 'pre_kinetic'
      indicator_count:  0-5 indicators present
      indicators:       dict of which indicators are active
      assessment:       structural narrative (apolitical)
    """
    target = (target or 'cuba').lower()
    target_cfg = _KINETIC_PRECURSOR_TARGETS.get(target)
    if not target_cfg:
        return {
            'target': target, 'label': target.title(), 'flag': '',
            'score': 0, 'tier': 'baseline', 'indicator_count': 0,
            'indicators': {}, 'assessment': f'Target "{target}" not configured for cadence tracking.',
        }

    detection = _detect_cadence_indicators(target, actor_results, articles)
    count = detection['count']
    score = count * 20  # 5 indicators * 20 = 100

    # Tier
    if count >= 5:
        tier = 'pre_kinetic'
        tier_label = 'PRE-KINETIC (cadence complete)'
    elif count >= 4:
        tier = 'developing'
        tier_label = 'CADENCE DEVELOPING (4/5 indicators)'
    elif count >= 3:
        tier = 'forming'
        tier_label = 'CADENCE FORMING (3/5 indicators)'
    elif count >= 1:
        tier = 'baseline'
        tier_label = 'BASELINE WITH SIGNALS'
    else:
        tier = 'baseline'
        tier_label = 'BASELINE'

    # Apolitical structural assessment
    active_names = [k.replace('_', ' ').title()
                    for k, v in detection['indicators'].items() if v]

    if tier == 'pre_kinetic':
        assessment = (
            f"All 5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"This is the structural signature of US executive sequencing toward kinetic action — "
            f"the same pattern that preceded the Venezuela January 2026 raid by ~21 days. "
            f"OBSERVATION ONLY: cadence detection is a tradecraft pattern, not a prediction. "
            f"Pattern may resolve through diplomacy, deterrence, or executive de-escalation. "
            f"Same indicators repeat regardless of which administration is in office."
        )
    elif tier == 'developing':
        assessment = (
            f"4/5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"Approaching the Venezuela 2026 pre-kinetic pattern threshold. "
            f"Missing indicator may emerge in next 3-7 days if cadence continues. "
            f"Observation, not prediction."
        )
    elif tier == 'forming':
        assessment = (
            f"3/5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"Cadence forming but not yet at developed threshold. "
            f"Pattern may either accelerate or dissipate. Worth daily monitoring."
        )
    elif count >= 1:
        assessment = (
            f"{count}/5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"Below cadence-formation threshold (3 needed). "
            f"Routine monitoring."
        )
    else:
        assessment = (
            f"No cadence indicators active for {target_cfg['label']}. "
            f"US posture toward target is below escalation-sequencing threshold."
        )

    return {
        'target':           target,
        'label':            target_cfg['label'],
        'flag':             target_cfg['flag'],
        'score':            score,
        'tier':             tier,
        'tier_label':       tier_label,
        'indicator_count':  count,
        'indicators':       detection['indicators'],
        'assessment':       assessment,
    }


def compute_kinetic_precursor_targets(actor_results, articles):
    """
    Scan all configured targets and return list of targets with elevated
    cadence scores (>= 'forming' tier). The "kinetic-precursor watch list."

    APOLITICAL: returns structural observation, sorted by score descending.
    """
    elevated = []
    for target_key in _KINETIC_PRECURSOR_TARGETS:
        result = compute_escalation_cadence_score(actor_results, articles, target_key)
        if result['indicator_count'] >= 1:
            elevated.append(result)

    elevated.sort(key=lambda r: r['score'], reverse=True)
    return elevated


print("[US Signal Interpreter] Module loaded -- v1.4.1 (plain So What)")
