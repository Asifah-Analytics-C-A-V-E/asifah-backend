"""
Asifah Analytics — Military Signal Interpreter v1.0.0
May 11, 2026

Analytical prose layer for the Military Tracker. Consumes scan_result data
(target_postures, theatre_groupings, chokepoint data, evacuation_alerts) and
produces bounded, FSO-grade analytical prose for the military.html frontend
and downstream consumers (GPI, rhetoric trackers reading mil-fingerprints).

ARCHITECTURAL PATTERN:
  Mirrors peru_signal_interpreter.py / chile_signal_interpreter.py shape:
    - build_theater_prose(scan_result)        → dict {theater_id: prose}
    - build_chokepoint_prose(scan_result)     → dict {chokepoint_id: prose}
    - build_convergence_prose(scan_result)    → dict {convergence_label: prose}
    - build_evacuation_prose(scan_result)     → str (single block, all evacs)
    - build_top_signals(scan_result)          → list[dict] canonical schema
    - build_executive_summary(scan_result)    → str (1-paragraph top-line)

DESIGN PRINCIPLES:
  1. STRICTLY BOUNDED — every prose block is 2-3 sentences max. No unbounded
     generation. Templates drive structure; dynamic data injection fills slots.
  2. ANALYTICAL ONLY — never market translation. No tickers (XLE/RTX/etc.).
     No "watch defense primes." No CAVE-territory output.
  3. APOLITICAL — no partisan coloring on US posture. Same analytical frame
     regardless of which administration directs the posture.
  4. PER-OPTION-C STRATEGY — baseline prose for 5 major regions ALWAYS;
     escalatory prose conditional on elevated+ alert level.
  5. FSO-GRADE TONE — diplomatic-watch-officer voice. Active actors named.
     Specific signals quoted. Implications clear without speculation.

COPYRIGHT © 2025-2026 Asifah Analytics. All rights reserved.
"""

# ============================================================
# IMPORTS
# ============================================================

# No external dependencies — pure Python. Interpreter is a stateless
# transformation layer over scan_result data.


# ============================================================
# CONFIGURATION CONSTANTS
# ============================================================

# Regional zones we ALWAYS emit baseline prose for (per Option C).
# Maps theatre_id (from REGIONAL_THEATRES in military_tracker.py)
# → display name + baseline-prose template.
REGIONAL_BASELINE_TEMPLATES = {
    'middle_east': {
        'display': 'Middle East / CENTCOM',
        'baseline': (
            'CENTCOM AOR baseline. Routine ME naval-air posture across the '
            'Gulf, Levant, and Red Sea corridors with no theatre-wide escalation signal.'
        ),
        'context_actors': ['iran', 'israel', 'iraq', 'saudi_arabia', 'uae', 'jordan'],
    },
    'asia_pacific': {
        'display': 'Asia-Pacific / INDOPACOM',
        'baseline': (
            'INDOPACOM AOR baseline. Standard PLAN, ROK-US-DPRK, and Taiwan-Strait '
            'routine activity with no theatre-wide escalation signal.'
        ),
        'context_actors': ['china', 'taiwan'],
    },
    'europe': {
        'display': 'Europe / EUCOM',
        'baseline': (
            'EUCOM AOR baseline. Routine NATO eastern-flank posture with Russia-Ukraine '
            'corridor at established conflict tempo and no broader theatre escalation signal.'
        ),
        'context_actors': ['russia', 'ukraine', 'nato', 'poland', 'greenland'],
    },
    'western_hemisphere': {
        'display': 'Western Hemisphere / SOUTHCOM-NORTHCOM',
        'baseline': (
            'WHA AOR baseline. Routine SOUTHCOM Caribbean and counter-narcotics posture '
            'with no theatre-wide escalation signal.'
        ),
        'context_actors': ['venezuela', 'cuba', 'haiti', 'panama', 'colombia',
                           'mexico', 'brazil'],
    },
    'global_northcom': {
        'display': 'Global / NORTHCOM',
        'baseline': (
            'NORTHCOM and global US-anchor posture at baseline. No homeland-defense '
            'escalation indicators or unusual force-projection signals from the US anchor.'
        ),
        'context_actors': ['us'],
    },
}

# Critical-event keywords surfaced by chokepoint prose builder.
# Each key maps to phrasing inserted into the prose when present.
# Order matters — most severe phrasing first.
CHOKEPOINT_CRITICAL_PHRASES = [
    ('mining',                    'naval mining activity'),
    ('mine threat',               'naval mining activity'),
    ('vessel struck',             'kinetic strikes on commercial vessels'),
    ('tanker attacked',           'kinetic strikes on commercial tankers'),
    ('tanker struck',             'kinetic strikes on commercial tankers'),
    ('ship attacked',             'attacks on commercial shipping'),
    ('anti-ship missile',         'anti-ship missile activity'),
    ('blockade',                  'blockade signaling'),
    ('closed to traffic',         'transit closure to commercial traffic'),
    ('closed to commercial',      'transit closure to commercial traffic'),
    ('closed to shipping',        'transit closure to commercial shipping'),
    ('cape of good hope',         'commercial rerouting via the Cape of Good Hope'),
    ('rerouting',                 'commercial rerouting underway'),
    ('jwc listed',                'Lloyd\'s JWC war-risk listing'),
    ('joint war committee',       'Lloyd\'s JWC war-risk listing'),
    ('war risk',                  'war-risk insurance escalation'),
    ('convoy escort',             'convoy escort operations'),
    ('escorted transit',          'escorted commercial transit'),
    ('seized vessel',             'vessel seizure'),
    ('vessel boarded',            'vessel boarding incidents'),
    ('hijacked',                  'vessel hijacking'),
]

# Chokepoint display names for prose (more readable than slugs).
CHOKEPOINT_DISPLAY = {
    'hormuz':           'Strait of Hormuz',
    'bab_el_mandeb':    'Bab el-Mandeb',
    'suez':             'Suez Canal',
    'taiwan_strait':    'Taiwan Strait',
    'south_china_sea':  'South China Sea',
    'malacca':          'Strait of Malacca',
    'sunda_strait':     'Sunda Strait',
    'bosporus':         'Turkish Straits / Bosporus',
    'gibraltar':        'Strait of Gibraltar',
    'sicily_strait':    'Strait of Sicily',
    'panama_canal':     'Panama Canal',
    'magellan':         'Strait of Magellan',
    'baltic':           'Baltic Sea approaches',
    'arctic':           'Arctic GIUK / Greenland Sea',
    'bering_strait':    'Bering Strait',
    'black_sea':        'Black Sea',
    'mediterranean':    'Eastern Mediterranean',
    'caribbean':        'Caribbean Basin / Florida Straits',
}

# Country display names (richer than the slug). Falls back to slug.title() if missing.
COUNTRY_DISPLAY = {
    'us':            'the United States',
    'iran':          'Iran',
    'israel':        'Israel',
    'iraq':          'Iraq',
    'russia':        'Russia',
    'china':         'China',
    'taiwan':        'Taiwan',
    'ukraine':       'Ukraine',
    'venezuela':     'Venezuela',
    'cuba':          'Cuba',
    'haiti':         'Haiti',
    'panama':        'Panama',
    'colombia':      'Colombia',
    'mexico':        'Mexico',
    'brazil':        'Brazil',
    'saudi_arabia':  'Saudi Arabia',
    'uae':           'the UAE',
    'jordan':        'Jordan',
    'qatar':         'Qatar',
    'kuwait':        'Kuwait',
    'egypt':         'Egypt',
    'turkey':        'Turkey',
    'greenland':     'Greenland',
    'poland':        'Poland',
    'nato':          'NATO',
}

# Alert-level phrasing maps. Used to inject correct severity wording.
COUNTRY_LEVEL_PHRASES = {
    'normal':   'baseline activity',
    'elevated': 'elevated posture',
    'high':     'high-tempo posture',
    'surge':    'surge-level posture',
}

CHOKEPOINT_LEVEL_PHRASES = {
    'open':       'open',
    'monitored':  'monitored',
    'contested':  'contested',
    'disrupted':  'disrupted',
}

# Numeric ranks for sorting/comparing severity.
COUNTRY_LEVEL_RANK    = {'normal': 0, 'elevated': 1, 'high': 2, 'surge': 3}
CHOKEPOINT_LEVEL_RANK = {'open': 0, 'monitored': 1, 'contested': 2, 'disrupted': 3}


# ============================================================
# HELPERS
# ============================================================

def _safe_dict(d):
    """Return d if dict, else {}."""
    return d if isinstance(d, dict) else {}


def _safe_list(l):
    """Return l if list, else []."""
    return l if isinstance(l, list) else []


def _country_display(country_id):
    """Resolve country display name."""
    if not country_id:
        return ''
    return COUNTRY_DISPLAY.get(country_id, country_id.replace('_', ' ').title())


def _chokepoint_display(cp_id):
    """Resolve chokepoint display name."""
    if not cp_id:
        return ''
    return CHOKEPOINT_DISPLAY.get(cp_id, cp_id.replace('_', ' ').title())


def _extract_critical_phrases_for_signals(top_signals):
    """Inspect a chokepoint's top_signals and return a list of unique critical
    phrases present (deduplicated by topic, ordered by severity).

    Topic-grouping prevents redundancy like 'rerouting via cape of good hope,
    commercial rerouting underway' — both keywords fire on the same article
    but they describe the same phenomenon."""
    # Group keywords by topic so same-topic matches dedupe to one phrase
    KEYWORD_TOPICS = {
        'mining':                 ('mining', 'naval mining activity'),
        'mine threat':            ('mining', 'naval mining activity'),
        'vessel struck':          ('vessel_strike', 'kinetic strikes on commercial vessels'),
        'tanker attacked':        ('vessel_strike', 'kinetic strikes on commercial tankers'),
        'tanker struck':          ('vessel_strike', 'kinetic strikes on commercial tankers'),
        'ship attacked':          ('vessel_strike', 'attacks on commercial shipping'),
        'anti-ship missile':      ('vessel_strike', 'anti-ship missile activity'),
        'blockade':               ('closure', 'blockade signaling'),
        'closed to traffic':      ('closure', 'transit closure to commercial traffic'),
        'closed to commercial':   ('closure', 'transit closure to commercial traffic'),
        'closed to shipping':     ('closure', 'transit closure to commercial shipping'),
        'cape of good hope':      ('rerouting', 'commercial rerouting via the Cape of Good Hope'),
        'rerouting':              ('rerouting', 'commercial rerouting underway'),
        'jwc listed':             ('insurance', 'Lloyd\'s JWC war-risk listing'),
        'joint war committee':    ('insurance', 'Lloyd\'s JWC war-risk listing'),
        'war risk':               ('insurance', 'war-risk insurance escalation'),
        'convoy escort':          ('escort', 'convoy escort operations'),
        'escorted transit':       ('escort', 'escorted commercial transit'),
        'seized vessel':          ('boarding', 'vessel seizure'),
        'vessel boarded':         ('boarding', 'vessel boarding incidents'),
        'hijacked':               ('boarding', 'vessel hijacking'),
    }

    found = []
    seen_topics = set()
    for sig in top_signals or []:
        title = (sig.get('title') or '').lower()
        # Match keywords in declaration order (most severe first when iterating
        # the original CHOKEPOINT_CRITICAL_PHRASES list)
        for kw, phrase in CHOKEPOINT_CRITICAL_PHRASES:
            if kw in title:
                topic = KEYWORD_TOPICS.get(kw, (kw, phrase))[0]
                if topic not in seen_topics:
                    found.append(phrase)
                    seen_topics.add(topic)
                # Once we've matched a keyword for this signal,
                # continue scanning OTHER keywords on this same signal —
                # different topics might also be present in the same headline.
    return found


def _truncate(text, max_chars=200):
    """Truncate text to a max length, breaking on word boundary."""
    if not text or len(text) <= max_chars:
        return text or ''
    cut = text[:max_chars].rsplit(' ', 1)[0]
    return cut + '…'


# ============================================================
# THEATER PROSE BUILDER
# ============================================================

def build_theater_prose(scan_result):
    """
    Build per-theater analytical prose. Returns:
        {
            'middle_east': {'level': 'surge', 'prose': '...', 'display': '...'},
            'asia_pacific': {...},
            ...
        }

    Always emits baseline + display for ALL 5 regions per Option C strategy.
    Layers escalatory prose when theatre alert_level is elevated+.
    """
    scan_result = _safe_dict(scan_result)
    theatre_groupings = _safe_dict(scan_result.get('theatre_groupings'))
    actor_summaries   = _safe_dict(scan_result.get('actor_summaries'))

    output = {}

    for theatre_id, tmpl in REGIONAL_BASELINE_TEMPLATES.items():
        theatre_data = _safe_dict(theatre_groupings.get(theatre_id))
        alert_level = theatre_data.get('alert_level', 'normal')
        display = tmpl['display']

        # Default — baseline prose
        prose = tmpl['baseline']

        # If theatre is escalating, layer in actor-specific phrasing
        if alert_level in ('elevated', 'high', 'surge'):
            actors_in_theatre = _safe_dict(theatre_data.get('actors'))
            elevated_actors = []
            for actor_id, actor_data in actors_in_theatre.items():
                actor_data = _safe_dict(actor_data)
                if actor_data.get('alert_level') in ('elevated', 'high', 'surge'):
                    elevated_actors.append((actor_id, actor_data.get('alert_level')))
            elevated_actors.sort(
                key=lambda x: COUNTRY_LEVEL_RANK.get(x[1], 0), reverse=True)

            if elevated_actors:
                # Build "Actor (level), Actor (level)" phrasing for top 3
                actor_phrases = []
                for actor_id, lvl in elevated_actors[:3]:
                    actor_phrases.append(
                        f"{_country_display(actor_id)} at {COUNTRY_LEVEL_PHRASES.get(lvl, lvl)}"
                    )
                actor_str = ', '.join(actor_phrases[:-1])
                if len(actor_phrases) > 1:
                    actor_str += f', and {actor_phrases[-1]}'
                else:
                    actor_str = actor_phrases[0]

                # Theater-level severity phrasing
                if alert_level == 'surge':
                    prose = (
                        f"{tmpl['display']} at SURGE-LEVEL ESCALATION — "
                        f"{actor_str}. Multi-actor military pressure converging "
                        f"in the AOR; watch for cascade across adjacent theaters."
                    )
                elif alert_level == 'high':
                    prose = (
                        f"{tmpl['display']} at HIGH-TEMPO posture — "
                        f"{actor_str}. Sustained military pressure across multiple "
                        f"actors; track for further escalation triggers."
                    )
                else:  # elevated
                    prose = (
                        f"{tmpl['display']} elevated above baseline — "
                        f"{actor_str}. Above-routine posture without crossing into "
                        f"high-tempo or surge thresholds."
                    )

        output[theatre_id] = {
            'level':   alert_level,
            'prose':   prose,
            'display': display,
        }

    return output


# ============================================================
# CHOKEPOINT PROSE BUILDER
# ============================================================

def build_chokepoint_prose(scan_result):
    """
    Build per-chokepoint analytical prose. Returns:
        {
            'hormuz':        {'level': 'disrupted', 'prose': '...', 'display': '...'},
            'bab_el_mandeb': {...},
            ...
        }

    Only includes chokepoints at 'monitored' or higher per Option C
    (baseline prose for 5 regions; conditional for chokepoints).
    'disrupted' and 'contested' get full critical-signal callouts.
    'monitored' gets a brief watch-prose without alarmist phrasing.

    NOTE: The fingerprint write logic is in military_tracker.py — this
    interpreter is read-only over the scan_result. Chokepoint data is
    expected to live at scan_result['chokepoint_postures'][cp_id] which
    the tracker will populate on the next refresh after wiring this in.
    """
    scan_result = _safe_dict(scan_result)
    chokepoint_postures = _safe_dict(scan_result.get('chokepoint_postures'))

    output = {}

    for cp_id, cp_data in chokepoint_postures.items():
        cp_data = _safe_dict(cp_data)
        level = cp_data.get('alert_level', 'open')

        # Skip 'open' chokepoints — no prose (per Option C, conditional only)
        if level == 'open':
            continue

        display = _chokepoint_display(cp_id)
        signal_count = cp_data.get('signal_count', 0)
        critical_count = cp_data.get('critical_signal_count', 0)
        top_signals = _safe_list(cp_data.get('top_signals'))

        critical_phrases = _extract_critical_phrases_for_signals(top_signals)

        if level == 'disrupted':
            # Most severe — name specific critical phenomena
            if critical_phrases:
                phrase_str = ', '.join(critical_phrases[:3])
                prose = (
                    f"{display} DISRUPTED — {phrase_str} detected this scan "
                    f"({signal_count} total signals, {critical_count} critical-event "
                    f"signals). Commercial transit risk at peak; monitor adjacent "
                    f"chokepoints for cascade disruption."
                )
            else:
                prose = (
                    f"{display} DISRUPTED — {signal_count} signals this scan "
                    f"crossing the disruption threshold. Active interruption to "
                    f"normal commercial transit pattern."
                )

        elif level == 'contested':
            if critical_phrases:
                phrase_str = ', '.join(critical_phrases[:3])
                prose = (
                    f"{display} CONTESTED — {phrase_str} reported "
                    f"({signal_count} signals). Active confrontation pattern "
                    f"elevating commercial transit risk; watch for shift to "
                    f"disrupted-level signals."
                )
            else:
                prose = (
                    f"{display} CONTESTED — {signal_count} signals indicating "
                    f"active confrontation activity. Above-routine pressure on "
                    f"commercial transit through the corridor."
                )

        else:  # monitored
            prose = (
                f"{display} monitored — {signal_count} signals above baseline "
                f"this scan, no kinetic-event indicators yet. Routine "
                f"watch-state for the corridor."
            )

        output[cp_id] = {
            'level':   level,
            'prose':   prose,
            'display': display,
        }

    return output


# ============================================================
# CONVERGENCE PROSE BUILDER
# ============================================================

def build_convergence_prose(scan_result):
    """
    Build per-convergence-pair analytical prose. Returns:
        {
            'hormuz_bam': {'level': 'contested', 'prose': '...', 'display': '...'},
            ...
        }

    Convergences are populated in scan_result['chokepoint_convergences']
    by the tracker. Each entry has the rationale prose pre-written in
    military_tracker.py's CHOKEPOINT_CONVERGENCE_PAIRS dict — we surface
    it here with severity framing.
    """
    scan_result = _safe_dict(scan_result)
    convergences = _safe_dict(scan_result.get('chokepoint_convergences'))

    output = {}

    for label, conv_data in convergences.items():
        conv_data = _safe_dict(conv_data)
        if not conv_data.get('active'):
            continue

        level = conv_data.get('level', 'contested')
        chokepoint_levels = _safe_dict(conv_data.get('chokepoint_levels'))
        rationale = conv_data.get('rationale', '')

        cp_phrases = []
        for cp_id, cp_lvl in chokepoint_levels.items():
            cp_phrases.append(f"{_chokepoint_display(cp_id)} at "
                              f"{CHOKEPOINT_LEVEL_PHRASES.get(cp_lvl, cp_lvl)}")
        cp_str = ' + '.join(cp_phrases)

        if level == 'disrupted':
            prose = (
                f"COUPLED-DISRUPTION FINGERPRINT: {cp_str}. "
                f"{rationale} Both chokepoints simultaneously crossing the disruption "
                f"threshold — track upstream/downstream commercial-traffic impact."
            )
        else:
            prose = (
                f"Coupled-pressure fingerprint active: {cp_str}. "
                f"{rationale} Watch for shift toward simultaneous disruption."
            )

        output[label] = {
            'level':   level,
            'prose':   prose,
            'display': label.replace('_', ' / ').upper(),
        }

    return output


# ============================================================
# EVACUATION PROSE BUILDER
# ============================================================

def build_evacuation_prose(scan_result):
    """
    Build prose summarizing active NEO/embassy-drawdown signals.
    Returns single paragraph string, or empty string if no evac signals.
    """
    scan_result = _safe_dict(scan_result)
    evac_alerts = _safe_list(scan_result.get('evacuation_alerts'))

    if not evac_alerts:
        return ''

    # Group by actor/country
    by_actor = {}
    for evac in evac_alerts:
        evac = _safe_dict(evac)
        actor = evac.get('actor', 'unknown')
        if actor not in by_actor:
            by_actor[actor] = []
        by_actor[actor].append(evac)

    actors_with_count = []
    subtypes_seen = set()
    for actor, evacs in by_actor.items():
        actors_with_count.append((actor, len(evacs)))
        for e in evacs:
            sub = e.get('subtype', 'unspecified')
            if sub != 'unspecified':
                subtypes_seen.add(sub.replace('_', ' '))

    actor_str = ', '.join(f"{a} ({n})" for a, n in actors_with_count[:4])
    sub_str = ', '.join(sorted(subtypes_seen)[:5]) if subtypes_seen else ''

    if sub_str:
        return (
            f"ACTIVE NEO / DRAWDOWN SIGNALS: {len(evac_alerts)} signals across "
            f"{len(by_actor)} actor(s) — {actor_str}. Signal types: {sub_str}. "
            f"FSOs and embassy staff in affected AORs should track parent-cable cadence."
        )
    return (
        f"ACTIVE NEO / DRAWDOWN SIGNALS: {len(evac_alerts)} signals across "
        f"{len(by_actor)} actor(s) — {actor_str}. FSOs and embassy staff in "
        f"affected AORs should track parent-cable cadence."
    )


# ============================================================
# TOP SIGNALS — CANONICAL SCHEMA (for GPI consumption)
# ============================================================

def build_top_signals(scan_result):
    """
    Build a canonical-schema signals list compatible with the WHA / ME / Asia
    regional BLUF synthesis pattern. Each signal has short_text + long_text
    + level + priority + theatre + category fields.

    Mirrors peru_signal_interpreter.build_top_signals shape so the GPI can
    consume military signals identically to rhetoric signals.
    """
    scan_result = _safe_dict(scan_result)
    theatre_groupings   = _safe_dict(scan_result.get('theatre_groupings'))
    chokepoint_postures = _safe_dict(scan_result.get('chokepoint_postures'))
    convergences        = _safe_dict(scan_result.get('chokepoint_convergences'))
    evac_alerts         = _safe_list(scan_result.get('evacuation_alerts'))
    actor_summaries     = _safe_dict(scan_result.get('actor_summaries'))

    signals = []

    # 1. Theater signals (only escalated)
    for theatre_id, tmpl in REGIONAL_BASELINE_TEMPLATES.items():
        td = _safe_dict(theatre_groupings.get(theatre_id))
        lvl = td.get('alert_level', 'normal')
        rank = COUNTRY_LEVEL_RANK.get(lvl, 0)
        if rank < 1:    # only elevated+
            continue

        actors_in = _safe_dict(td.get('actors'))
        active_count = sum(1 for _id, ad in actors_in.items()
                            if _safe_dict(ad).get('alert_level') in
                                ('elevated', 'high', 'surge'))

        signals.append({
            'priority':   8 + rank,
            'category':   'mil_theatre',
            'theatre':    theatre_id,
            'level':      rank,
            'level_name': lvl,
            'icon':       '🪖',
            'color':      '#dc2626' if rank >= 2 else '#f59e0b',
            'short_text': f"🪖 {tmpl['display']}: {COUNTRY_LEVEL_PHRASES.get(lvl)}",
            'long_text':  (f"{tmpl['display']} at {lvl} — {active_count} actors "
                            f"above baseline."),
        })

    # 2. Chokepoint signals (contested+ only — Option C strategy)
    for cp_id, cp_data in chokepoint_postures.items():
        cp_data = _safe_dict(cp_data)
        lvl = cp_data.get('alert_level', 'open')
        rank = CHOKEPOINT_LEVEL_RANK.get(lvl, 0)
        if rank < 2:    # contested+
            continue

        critical_count = cp_data.get('critical_signal_count', 0)
        signal_count = cp_data.get('signal_count', 0)

        signals.append({
            'priority':    9 + rank,    # chokepoints rank slightly higher than theatres
            'category':    'mil_chokepoint',
            'theatre':     cp_id,
            'level':       rank,
            'level_name':  lvl,
            'icon':        '🚢' if lvl != 'disrupted' else '🛑',
            'color':       '#dc2626' if rank >= 3 else '#f59e0b',
            'short_text':  f"🚢 {_chokepoint_display(cp_id)}: {lvl.upper()}",
            'long_text':   (f"{_chokepoint_display(cp_id)} {lvl} — {signal_count} "
                            f"signals ({critical_count} critical-event)."),
        })

    # 3. Convergence signals (active only)
    for label, conv_data in convergences.items():
        conv_data = _safe_dict(conv_data)
        if not conv_data.get('active'):
            continue
        lvl = conv_data.get('level', 'contested')
        rank = CHOKEPOINT_LEVEL_RANK.get(lvl, 2)

        signals.append({
            'priority':    11 + rank,    # highest priority — convergences are rarest signals
            'category':    'mil_convergence',
            'theatre':     label,
            'level':       rank,
            'level_name':  lvl,
            'icon':        '⚡',
            'color':       '#dc2626',
            'short_text':  f"⚡ COUPLED CHOKEPOINTS: {label.replace('_', ' / ').upper()}",
            'long_text':   (f"Chokepoint convergence — {label} active at {lvl}. "
                            f"{conv_data.get('rationale', '')[:150]}"),
        })

    # 4. Evacuation signal (single signal if any active)
    if evac_alerts:
        actor_set = set()
        for e in evac_alerts:
            a = _safe_dict(e).get('actor', '')
            if a:
                actor_set.add(a)
        signals.append({
            'priority':    12,    # NEO is always a top signal
            'category':    'mil_evacuation',
            'theatre':     'global',
            'level':       3,
            'level_name':  'active',
            'icon':        '🚨',
            'color':       '#dc2626',
            'short_text':  f"🚨 NEO / DRAWDOWN: {len(evac_alerts)} signals",
            'long_text':   (f"Active NEO / embassy-drawdown signals — "
                            f"{len(evac_alerts)} alerts across "
                            f"{len(actor_set)} actor(s)."),
        })

    # Sort by priority desc, then return top 10
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals[:10]


# ============================================================
# EXECUTIVE SUMMARY
# ============================================================

def build_executive_summary(scan_result):
    """
    Build top-line 1-paragraph executive summary surfacing only the
    highest-priority items across theaters, chokepoints, convergences, NEOs.
    """
    scan_result = _safe_dict(scan_result)

    theatre_groupings   = _safe_dict(scan_result.get('theatre_groupings'))
    chokepoint_postures = _safe_dict(scan_result.get('chokepoint_postures'))
    convergences        = _safe_dict(scan_result.get('chokepoint_convergences'))
    evac_alerts         = _safe_list(scan_result.get('evacuation_alerts'))

    # Surge or high theatres
    hot_theatres = [
        (tid, td) for tid, td in theatre_groupings.items()
        if _safe_dict(td).get('alert_level') in ('high', 'surge')
    ]
    # Disrupted or contested chokepoints
    hot_chokepoints = [
        (cp, cd) for cp, cd in chokepoint_postures.items()
        if _safe_dict(cd).get('alert_level') in ('contested', 'disrupted')
    ]
    # Active convergences
    active_convergences = [
        (lab, cd) for lab, cd in convergences.items()
        if _safe_dict(cd).get('active')
    ]

    # ── Build summary from highest-priority items down ──
    parts = []

    # Lead with NEO if active (biggest FSO concern)
    if evac_alerts:
        parts.append(
            f"⚠️ {len(evac_alerts)} active NEO / embassy-drawdown signal(s) "
            f"across {len({_safe_dict(e).get('actor', '') for e in evac_alerts})} actor(s)."
        )

    # Convergences next (rare and load-bearing)
    if active_convergences:
        conv_names = [lab.replace('_', '+').upper() for lab, _ in active_convergences[:2]]
        parts.append(
            f"Coupled-pressure fingerprint(s) firing: {', '.join(conv_names)}."
        )

    # Hot chokepoints
    if hot_chokepoints:
        cp_phrases = []
        # Disrupted first
        for cp, cd in hot_chokepoints:
            if _safe_dict(cd).get('alert_level') == 'disrupted':
                cp_phrases.append(f"{_chokepoint_display(cp)} DISRUPTED")
        for cp, cd in hot_chokepoints:
            if _safe_dict(cd).get('alert_level') == 'contested':
                cp_phrases.append(f"{_chokepoint_display(cp)} contested")
        if cp_phrases:
            parts.append(f"Chokepoint pressure: {'; '.join(cp_phrases[:3])}.")

    # Hot theatres (only if no chokepoint or convergence already implies them)
    if hot_theatres and not hot_chokepoints and not active_convergences:
        t_phrases = []
        for tid, td in hot_theatres:
            tmpl = REGIONAL_BASELINE_TEMPLATES.get(tid, {})
            display = tmpl.get('display', tid)
            lvl = _safe_dict(td).get('alert_level', '')
            t_phrases.append(f"{display} at {COUNTRY_LEVEL_PHRASES.get(lvl, lvl)}")
        parts.append(f"Theatre pressure: {'; '.join(t_phrases[:3])}.")

    # Default if nothing above baseline
    if not parts:
        active_actors = scan_result.get('active_actors', [])
        if active_actors:
            return (
                f"Global military posture at baseline. {len(active_actors)} actor(s) "
                f"with above-routine signal activity but no theatre-wide escalation, "
                f"chokepoint contestation, or NEO signals."
            )
        return (
            "Global military posture at baseline. No theatre-wide escalation, "
            "chokepoint contestation, or NEO signals detected this scan."
        )

    return ' '.join(parts)


# ============================================================
# UMBRELLA BUILDER — single call returns full prose package
# ============================================================

def build_full_interpretation(scan_result):
    """
    One-call wrapper that returns the complete interpretation package.

    Returns:
        {
            'executive_summary':   str,
            'theater_prose':       dict,
            'chokepoint_prose':    dict,
            'convergence_prose':   dict,
            'evacuation_prose':    str,
            'top_signals':         list[dict],
            'interpreter_version': '1.0.0',
        }
    """
    return {
        'executive_summary':   build_executive_summary(scan_result),
        'theater_prose':       build_theater_prose(scan_result),
        'chokepoint_prose':    build_chokepoint_prose(scan_result),
        'convergence_prose':   build_convergence_prose(scan_result),
        'evacuation_prose':    build_evacuation_prose(scan_result),
        'top_signals':         build_top_signals(scan_result),
        'interpreter_version': '1.0.0',
    }


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == '__main__':
    """Quick self-test with synthetic scan_result."""
    print("[Military Interpreter] Self-test running...")

    synthetic = {
        'theatre_groupings': {
            'middle_east': {
                'alert_level': 'surge',
                'actors': {
                    'iran': {'alert_level': 'surge'},
                    'us':   {'alert_level': 'high'},
                },
            },
            'asia_pacific': {
                'alert_level': 'elevated',
                'actors': {
                    'china':  {'alert_level': 'elevated'},
                    'taiwan': {'alert_level': 'elevated'},
                },
            },
            'europe':             {'alert_level': 'normal', 'actors': {}},
            'western_hemisphere': {'alert_level': 'normal', 'actors': {}},
            'global_northcom':    {'alert_level': 'high',
                                   'actors': {'us': {'alert_level': 'high'}}},
        },
        'chokepoint_postures': {
            'hormuz': {
                'alert_level':           'disrupted',
                'signal_count':          4,
                'critical_signal_count': 2,
                'top_signals': [
                    {'title': 'IRGC mining strait of hormuz reported'},
                    {'title': 'Tanker attacked near Hormuz'},
                ],
            },
            'bab_el_mandeb': {
                'alert_level':           'contested',
                'signal_count':          3,
                'critical_signal_count': 3,
                'top_signals': [
                    {'title': 'Houthi anti-ship missile attack on commercial vessel'},
                    {'title': 'Shippers rerouting via cape of good hope'},
                ],
            },
        },
        'chokepoint_convergences': {
            'hormuz_bam': {
                'active':            True,
                'level':             'contested',
                'chokepoint_levels': {'hormuz': 'disrupted', 'bab_el_mandeb': 'contested'},
                'rationale':         ('Iran-coupled — IRGC at Hormuz + Houthi proxies at '
                                       'BAM. Simultaneous contestation = supply-chain black swan.'),
            },
        },
        'evacuation_alerts': [
            {'subtype': 'embassy_drawdown', 'actor': 'United States',
             'title': 'US embassy Baghdad orders nonessential staff drawdown'},
        ],
        'active_actors': ['iran', 'us', 'china', 'taiwan'],
    }

    pkg = build_full_interpretation(synthetic)

    print("\n=== EXECUTIVE SUMMARY ===")
    print(pkg['executive_summary'])
    print("\n=== THEATER PROSE ===")
    for tid, td in pkg['theater_prose'].items():
        print(f"  [{td['level'].upper()}] {tid}: {td['prose']}")
    print("\n=== CHOKEPOINT PROSE ===")
    for cpid, cpd in pkg['chokepoint_prose'].items():
        print(f"  [{cpd['level'].upper()}] {cpid}: {cpd['prose']}")
    print("\n=== CONVERGENCE PROSE ===")
    for label, cd in pkg['convergence_prose'].items():
        print(f"  [{cd['level'].upper()}] {label}: {cd['prose']}")
    print("\n=== EVACUATION PROSE ===")
    print(f"  {pkg['evacuation_prose']}")
    print("\n=== TOP SIGNALS ===")
    for s in pkg['top_signals'][:5]:
        print(f"  [P{s['priority']}] {s['short_text']}")
        print(f"        long: {s['long_text'][:120]}")

    print("\n✅ SELF-TEST COMPLETE")
