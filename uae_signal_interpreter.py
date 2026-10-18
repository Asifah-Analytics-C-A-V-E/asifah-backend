"""
uae_signal_interpreter.py -- Asifah Analytics ME Backend -- v1.1.0 Oct 11 2026
  (v1.0.0 Jul 2026. v1.1.0 = dead calm guard fixed, duplicate definitions
   removed, Peru/Afghanistan/Pakistan clone residue purged.)
Analyst layer for rhetoric_tracker_uae (aligned-hub node).
5-function contract as canon. DRIFT AXIS: the DUAL-TRACK BALANCE AXIS --
lifeline-dominant <-> friction-dominant. Bands: Lifeline-Dominant -> Mixed ->
Friction-Rising -> Friction-Dominant. Nets kinetic/friction pressure against the
commercial lifeline (Dubai trade, flights, diaspora finance). The doctrine made
quantitative: divergence between kinetic and commercial tracks IS the tell.
Estimative voice. Convergence, not prediction.
"""

# ============================================
# CONFIGURATION
# ============================================
# v1.1.0: `import re` and `from datetime import ...` removed -- neither name
# was referenced anywhere in this module.

# ONE version string, read by the load banner. Two hand-maintained copies is
# how a module reports one version in a log line and another in a payload.
MODULE_VERSION = '1.2.3'

LEVEL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']
ESCALATORY_LEVELS = {'elevated', 'high', 'surge'}

# Vector display names for prose
VECTOR_NAMES = {
    'kinetic_inbound': 'Kinetic Inbound',
    'israel_axis':     'Israel Axis',
    'iran_dual':       'Iran Dual-Track',
    'economic_hub':    'Economic Hub',
}

VECTOR_MEMBERS = {
    'kinetic_inbound': ('uae_mod_airdefense', 'houthi_uae'),
    'israel_axis':     ('israel_uae_axis', 'us_uae'),
    'iran_dual':       ('iran_uae_dual',),
    'economic_hub':    ('adnoc_energy', 'dp_world_ports', 'uae_leadership_mbz'),
}

# Actor display names for prose (cleaner than the formal `name` field)
ACTOR_PROSE_NAMES = {
    'uae_leadership_mbz':  'the leadership / MBZ line',
    'uae_mod_airdefense':  'UAE MOD / air defense',
    'houthi_uae':          'the Houthi inbound-threat file',
    'israel_uae_axis':     'the Israel defense axis',
    'iran_uae_dual':       'the Iran dual-track',
    'adnoc_energy':        'ADNOC / energy',
    'dp_world_ports':      'DP World / the ports hub',
    'us_uae':              'the US-UAE track',
}

# Off-ramp / de-escalation patterns (lowered urgency when present)
DEESCALATION_PATTERNS = [
    'talks', 'dialogue', 'negotiation', 'delegation', 'border reopen',
    'crossing reopen', 'ceasefire', 'agreement', 'aid resumption',
    'prisoner release', 'decree suspended', 'restrictions eased',
    'humanitarian exemption', 'trade resumed',
]

# ============================================
# HELPERS
# ============================================
def _level_rank(level):
    """Numeric rank for level comparison."""
    try:
        return LEVEL_ORDER.index(level)
    except ValueError:
        return 0


def _max_level(levels):
    """Return the highest level from a list."""
    if not levels:
        return 'low'
    return max(levels, key=_level_rank)


def _has_deescalation(actor_summary):
    """Check if an actor's articles contain de-escalation patterns."""
    text = ''
    for art in actor_summary.get('top_articles', []):
        text += ' ' + (art.get('title') or '').lower()
    return any(p in text for p in DEESCALATION_PATTERNS)


def _top_article_for_actor(actor_summary):
    """Get the single highest-scoring article for an actor (or None)."""
    arts = actor_summary.get('top_articles', [])
    return arts[0] if arts else None


def _format_source_pill(source_name, feed_type=''):
    """Return a tagged source string for citation."""
    feed_type = (feed_type or '').lower()
    if feed_type:
        return f"{source_name} ({feed_type})"
    return source_name


# ============================================
# TOP SIGNALS BUILDER
# ============================================
def _commodity_story_signal(commodity_pressure):
    """Composite pressure story signal -- mirrors the stability page's
    commodity alert banner so both pages tell one story. None when calm."""
    story = (commodity_pressure or {}).get('_pressure_story') or {}
    alert = (story.get('alert') or 'normal').lower()
    if alert == 'normal':
        return None
    LEVEL_MAP = {'elevated': 'elevated', 'high': 'high',
                 'critical': 'surge', 'surge': 'surge'}
    escalated = [c for c, a in (story.get('commodities') or {}).items()
                 if a and a != 'normal']
    esc_txt = (', '.join(sorted(escalated)) if escalated
               else 'tracked commodities')
    return {
        'category':   'commodity_coupling',
        'type':       'commodity_coupling',
        'level':      LEVEL_MAP.get(alert, 'elevated'),
        'icon':       '\u26cf\ufe0f',
        'short_text': ('Composite commodity pressure: ' + alert.upper() + ' -- '
                       + str(story.get('points', 0)) + ' pts \u00b7 '
                       + str(story.get('profile_count', 0)) + ' commodities tracked'),
        'long_text':  ('Composite news-signal pressure (weighted volume/severity '
                       'of matched reporting, NOT price) is at ' + alert.upper()
                       + ' across ' + esc_txt + '. UAE supply-risk premium is '
                       'partly a political risk premium -- read this composite against '
                       'the rhetoric vectors, which are scored on the same window.'),
        'source_link': '/uae-stability.html#commodities',
    }


def build_top_signals(actor_summaries, tripwires_global, commodity_pressure, crosstheater_amplifiers):
    """
    Build the canonical top_signals[] array for the UAE rhetoric tracker.

    Each signal has the canonical schema:
      {
        'short_text':  one-line headline (≤120 chars)
        'long_text':   2-4 sentence elaboration
        'level':       one of low/normal/elevated/high/surge
        'type':        actor_signal | tripwire | convergence | commodity_coupling | crosstheater
        'actor':       actor_id (or None)
        'sources':     list of {title, url, source} (top 3)
      }

    Sorted by level (surge first), then by signal-richness.
    """
    signals = []

    # ── 1. Tripwire signals (highest priority) ──
    seen_tripwires = set()
    for tw in tripwires_global or []:
        tw_id = tw.get('id')
        if tw_id in seen_tripwires:
            continue
        seen_tripwires.add(tw_id)
        actor_id = tw.get('actor')
        actor_data = actor_summaries.get(actor_id, {}) if actor_id else {}
        # Oct 18 2026: cite the articles that FIRED the tripwire (tracker
        # 'evidence'); fall back to the actor's top article only when a tracker
        # predates evidence. Live: 'Infrastructure Strike' cited an article
        # about conjoined-twin surgery because it was the actor's top story.
        _ev = []
        for _t in (tripwires_global or []):
            if _t.get('id') == tw_id:
                for _e in (_t.get('evidence') or []):
                    if _e.get('url') not in {x.get('url') for x in _ev}:
                        _ev.append(_e)
        top_art = None if _ev else (_top_article_for_actor(actor_data) if actor_data else None)
        sources = [{'title': e.get('title', ''), 'url': e.get('url', ''), 'source': e.get('source', '')}
                   for e in _ev[:3]]
        if top_art:
            sources.append({
                'title':  top_art.get('title', ''),
                'url':    top_art.get('url', ''),
                'source': top_art.get('source', ''),
            })

        # v1.2.0: _tripwire_prose returns ONE string (the long text). The old
        # line unpacked it into two names, which raised ValueError the first
        # time a tripwire fired live -- silently dropping the whole interpreter
        # (alignment drift included) to the tracker's builtin fallback.
        long_text = _tripwire_prose(tw_id, actor_id)
        short = "\u26a0 Tripwire: " + str(tw_id).replace('_', ' ').title()
        signals.append({
            'short_text': short,
            'long_text':  long_text,
            'level':      tw.get('severity', 'high'),
            'type':       'tripwire',
            'actor':      actor_id,
            'sources':    sources,
        })

    # ── 2. Convergence signals ──
    # When ≥2 vectors are at elevated+, signal a convergence
    vector_levels = {}
    for actor_id, actor in actor_summaries.items():
        vec = actor.get('vector')
        lvl = actor.get('level', 'low')
        if vec:
            existing = vector_levels.get(vec, 'low')
            if _level_rank(lvl) > _level_rank(existing):
                vector_levels[vec] = lvl
    elevated_vectors = [v for v, lv in vector_levels.items() if lv in ESCALATORY_LEVELS]
    if len(elevated_vectors) >= 2:
        sig = _convergence_signal(elevated_vectors, vector_levels, actor_summaries)
        if sig:
            signals.append(sig)

    # ── 3. Per-actor signals (only at elevated+) ──
    for actor_id, actor in actor_summaries.items():
        level = actor.get('level', 'low')
        if level not in ESCALATORY_LEVELS:
            continue
        # Skip if a tripwire already covered this actor at the same/higher severity
        actor_tw_levels = [
            tw.get('severity') for tw in tripwires_global or []
            if tw.get('actor') == actor_id
        ]
        if actor_tw_levels and _level_rank(_max_level(actor_tw_levels)) >= _level_rank(level):
            continue

        sig = _actor_signal(actor_id, actor)
        if sig:
            signals.append(sig)

    # ── 4. Commodity coupling signals ──
    for commodity_id, risk in (commodity_pressure or {}).items():
        if commodity_id.startswith('_'):
            continue  # reserved keys (e.g. _pressure_story) are not commodities
        if risk.get('alert_level') in ESCALATORY_LEVELS:
            sig = _commodity_coupling_signal(commodity_id, risk, actor_summaries)
            if sig:
                signals.append(sig)

    # ── 5. Cross-theater amplifier signals ──
    for amp_label, amp_data in (crosstheater_amplifiers or {}).items():
        if not isinstance(amp_data, dict):
            continue
        # v1.1.0: the gate was `amp_data.get('active')` alone. The sibling
        # fingerprints this reads are canonical crosstheater payloads, which
        # carry a numeric `level` and may carry no 'active' key at all -- in
        # which case every amplifier read as calm forever. Accept either, at
        # the platform's standard lit threshold of 2.
        _lvl = amp_data.get('level')
        _lvl = _lvl if isinstance(_lvl, (int, float)) else -1
        if not amp_data.get('active') and _lvl < 2:
            continue
        sig = _crosstheater_signal(amp_label, amp_data)
        if sig:
            signals.append(sig)

    # Sort: surge → high → elevated → normal → low; within same level, signals with sources first
    # v1.2.0: tripwires are pinned above everything. A tripwire is an event
    # assertion ("a strike happened"); a surge actor is a volume reading
    # ("lots of talk"). Sorting by level alone let surge-level rhetoric -- and
    # the commodity story forced into slot 0 -- outrank a confirmed strike.
    signals.sort(
        key=lambda s: (0 if s.get('type') == 'tripwire' else 1,
                       -_level_rank(s['level']), -len(s.get('sources', [])))
    )
    # Composite commodity story rides high when escalated (mirrors stability
    # page) -- but directly BELOW any tripwires, never above them.
    _cs = _commodity_story_signal(commodity_pressure)
    if _cs:
        _n_tw = sum(1 for s in signals if s.get('type') == 'tripwire')
        signals.insert(_n_tw, _cs)
    return signals[:12]   # cap at 12 -- UI shows ~8 by default


def _tripwire_prose(tw_id, actor_id):
    P = {
        'homeland_attack': (
            "Attack signals on UAE population/economic centers at tripwire confidence -- the Jan 2022 "
            "Abu Dhabi precedent class. Last cycle, homeland strikes repriced aviation routings, tourism "
            "risk, and air-defense procurement within the week, and produced the UAE's first Israeli-"
            "assisted intercept posture. Watch activation reporting and airport advisories."),
        'fujairah_maritime_incident': (
            "Fujairah maritime incident at tripwire confidence -- the May 2019 precedent site. The "
            "Hormuz-bypass terminus taking damage attacks the escape-route logic itself; war-risk "
            "premiums on UAE port calls are the fastest repricing channel. Watch anchorage advisories "
            "and hull-insurance reporting."),
        'israel_defense_deal': (
            "Israel-UAE defense-deal signals at tripwire confidence -- the Accords-goes-kinetic "
            "milestone class. Each deal integrates Gulf air defense with Israeli systems and reprices "
            "the regional deterrence read; the MIL tracker's israel_uae_defense amplifier pairs with "
            "this event. De-escalatory bilaterally; escalatory in Tehran's read."),
        'iran_trade_rupture': (
            "Iran-trade rupture signals at tripwire confidence -- the dual-track's lifeline polarity "
            "failing. Historically, commercial rupture alongside kinetic escalation is confirmation-via-"
            "commerce: the pattern that precedes broader break. The dual-track axis swings hard on this "
            "tripwire; watch whether flight and re-export vocabulary follows."),
        'barakah_threat': (
            "Barakah threat signals at tripwire confidence -- an escalation class by construction. "
            "Threat vocabulary against the first Arab nuclear plant carries a radiological dimension "
            "that reprices the entire regional risk picture regardless of execution probability."),
        'jebel_ali_disruption': (
            "Jebel Ali disruption signals at tripwire confidence -- a global logistics event. The "
            "region's largest port going dark transmits into worldwide supply-chain costs through the "
            "DP World network, not just Gulf ones. Watch operations statements and vessel-queue data."),
    }
    return P.get(tw_id, "Tripwire pattern fired at high confidence -- low-base-rate, high-impact event class.")


def _convergence_signal(elevated_vectors, vector_levels, actor_summaries):
    """When 2+ vectors are at elevated+, build a convergence signal."""
    vec_names = [VECTOR_NAMES.get(v, v) for v in elevated_vectors]
    max_level = _max_level([vector_levels[v] for v in elevated_vectors])
    short = f"⚡ Convergence: {' + '.join(vec_names[:2])}{' + …' if len(vec_names) > 2 else ''} at {max_level}"
    long_parts = [f"Multiple analytical vectors are simultaneously elevated:"]
    for v in elevated_vectors:
        lvl = vector_levels[v]
        long_parts.append(f"• {VECTOR_NAMES.get(v, v).title()} at {lvl}")
    long_parts.append(
        "Convergence is more analytically significant than any single vector. For an "
        "aligned hub the specific worry is the kinetic and commercial tracks moving "
        "TOGETHER: friction rising while the Dubai lifeline holds has historically read "
        "as contained, and the two breaking in the same window is the pattern that has "
        "preceded broader rupture. CONVERGENCE indicator, NOT a probability of action."
    )
    # v1.1.0: was `' '.join(...) if False else '\n'.join(...)` -- a ternary with
    # a constant-false test, i.e. a dead branch pretending to be a choice.
    long_text = '\n'.join(long_parts)
    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      max_level,
        'type':       'convergence',
        'actor':      None,
        'sources':    [],
    }


def _actor_signal(actor_id, actor):
    """Build a per-actor signal at elevated+."""
    name = ACTOR_PROSE_NAMES.get(actor_id, actor.get('name', actor_id))
    level = actor.get('level', 'normal')
    score = actor.get('score', 0)
    article_count = actor.get('article_count', 0)
    icon = actor.get('icon', '📊')

    # Detect de-escalation
    deescalation = _has_deescalation(actor)

    # Build short_text
    if deescalation and level in ('elevated', 'high'):
        # v1.1.0: "(dialogue / consulta previa)" -- consulta previa is the
        # Peruvian prior-consultation statute. Peru is not in this tracker.
        short = f"{icon} {name} — {level}, but de-escalatory vocabulary in the same window"
    elif level == 'surge':
        short = f"{icon} {name} — SURGE-level rhetoric ({article_count} signals)"
    elif level == 'high':
        short = f"{icon} {name} — high-level rhetoric tempo ({article_count} signals)"
    else:
        short = f"{icon} {name} — elevated rhetoric tempo ({article_count} signals)"

    # Build long_text — actor-specific framing
    long_text = _actor_specific_long_text(actor_id, actor, deescalation)

    # Sources
    sources = []
    for art in actor.get('top_articles', [])[:3]:
        sources.append({
            'title':  art.get('title', ''),
            'url':    art.get('url', ''),
            'source': art.get('source', ''),
        })

    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      level,
        'type':       'actor_signal',
        'actor':      actor_id,
        'sources':    sources,
    }


def _actor_specific_long_text(actor_id, actor, deescalation):
    lvl = (actor or {}).get('level', 'low')
    de  = " De-escalatory vocabulary is present in the same window -- read the tempo against it." if deescalation else ""
    P = {
        'uae_leadership_mbz':
            "Leadership / MBZ tempo at " + lvl + ". Presidential statements track the federation's "
            "strategic posture; sovereign-wealth vocabulary (ADIA/Mubadala direction) transmits into "
            "global asset positioning within quarters. Abu Dhabi-Dubai balance language is the quiet "
            "internal watch.",
        'uae_mod_airdefense':
            "UAE MOD / air-defense tempo at " + lvl + ". Intercept announcements are the friction "
            "track's most legible gauge -- activation tempo tracks the inbound cycle nearly one-to-one, "
            "and it feeds the dual-track balance axis directly on the friction side.",
        'houthi_uae':
            "Houthi inbound-threat file at " + lvl + " toward UAE targets. The Jan 2022 Abu Dhabi "
            "strikes are the precedent set; claim tempo plus named-target specificity moving together "
            "is the pre-strike pattern. Red Sea maritime vocabulary rides this file for UAE shipping.",
        'israel_uae_axis':
            "Israel defense axis at " + lvl + ". Deal, training, and transfer vocabulary (the EDGE-"
            "Rafael channel) at this tempo is the Accords-goes-kinetic story deepening -- each cycle "
            "integrates Gulf air defense with Israeli systems and hardens Tehran's read of the hub's "
            "alignment.",
        'iran_uae_dual':
            "Iran dual-track at " + lvl + " on a MIXED-POLARITY spoke -- the analyst question is WHICH "
            "vocabulary dominates: kinetic/threat (friction) or trade/flights/finance (lifeline). "
            "Lifeline holding while kinetics spike has historically read as contained; divergence "
            "between the tracks is itself the tell. The balance axis carries the measured read.",
        'adnoc_energy':
            "ADNOC / energy signal volume at " + lvl + ". Production guidance, Habshan-Fujairah bypass "
            "throughput, and Barakah status vocabulary -- the bypass is the UAE's Petroline logic, and "
            "OPEC+ quota friction with Riyadh rides this actor.",
        'dp_world_ports':
            "DP World / ports-hub tempo at " + lvl + ". Jebel Ali operations and network vocabulary at "
            "this tempo reads as the lifeline's commercial health -- the counter-side of the dual-track "
            "balance axis. War-risk premium reporting is the fastest confirmation gauge.",
        'us_uae':
            "US-UAE track at " + lvl + ". Al Dhafra posture, arms-package (the F-35 saga), and security-"
            "agreement vocabulary -- the American anchor read that pairs with the Israel axis on the "
            "aligned-hub side of the map.",
    }
    return P.get(actor_id, "Actor signal tempo at " + lvl + " versus baseline.") + de


def _commodity_coupling_signal(commodity_id, risk, actor_summaries):
    """Build a commodity-coupling signal from a supply-risk fingerprint."""
    role = risk.get('role', 'producer')
    rank = risk.get('rank')
    rank_str = f" (#{rank} globally)" if rank else ""
    alert = risk.get('alert_level', 'normal')
    sig_count = risk.get('signal_count', 0)
    top_signal = risk.get('top_signal') or {}

    short = f"⛏️ Commodity coupling: {commodity_id} {role}{rank_str} — {alert} pressure from sector signals"
    # v1.1.0: this used to say the coupling ran through "illicit_economy /
    # wheat/corridor channels". The UAE tracker has no such vectors -- its
    # four are kinetic_inbound, israel_axis, iran_dual and economic_hub.
    long_text = (
        f"The commodity tracker is reporting {alert}-level pressure on UAE's {commodity_id} "
        f"sector (UAE is a {role}{rank_str}). {sig_count} cross-tracker signals flagged. "
        f"This is a coupling event: the economic_hub vector -- Jebel Ali throughput, "
        f"Fujairah war-risk, DMCC flows -- is where UAE rhetoric meets {commodity_id} "
        f"supply, and the UAE's supply-risk premium is partly a political risk premium. "
        f"Watch for sector-rhetoric and price-impact alignment."
    )
    sources = []
    if top_signal.get('title'):
        sources.append({
            'title':  top_signal.get('title', ''),
            'url':    top_signal.get('url', ''),
            'source': top_signal.get('source', ''),
        })

    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      alert,
        'type':       'commodity_coupling',
        # v1.1.0: was hardcoded 'drug_economy' -- not a UAE actor, and not an
        # actor in any tracker this file ships beside. Commodity coupling is
        # a theatre-level read, not an actor's, so it carries no actor at all.
        'actor':      None,
        'sources':    sources,
    }


def _crosstheater_signal(amp_label, amp_data):
    """Signal for an active sibling-wheel fingerprint (absence-honest: only called when present)."""
    # v1.1.0 -- REALIGNED TO WHAT THE TRACKER ACTUALLY READS.
    # rhetoric_tracker_uae._read_crosstheater_amplifiers() reads exactly three
    # keys: iran_fingerprint, israel_fingerprint, saudi_fingerprint. The old
    # table had prose for pakistan_fingerprint and china_fingerprint -- neither
    # is ever fetched, so neither could ever render -- and NO prose for israel
    # or saudi, the two that are. The china entry described "extraction-track
    # positioning in Kabul (Mes Aynak, Amu Darya)", which is Afghanistan.
    prose = {
        'iran_fingerprint': (
            '\U0001f1ee\U0001f1f7 Iran wheel active -- friction-side amplification',
            'The Iran tracker\'s crosstheater fingerprint is live. Elevated Iranian '
            'theatre pressure has historically hardened both polarities of the UAE '
            'dual-track at once: kinetic threat vocabulary rises while the Dubai '
            're-export lifeline is simultaneously leaned on. Divergence between the '
            'two is the tell this amplifier sharpens.'),
        'israel_fingerprint': (
            '\U0001f1ee\U0001f1f1 Israel wheel active -- alignment-side amplification',
            'The Israel tracker\'s crosstheater fingerprint is live. The UAE is the '
            'Gulf\'s most forward-leaning Accords signatory, so Israeli theatre '
            'pressure transmits into the israel_axis vector directly -- defense '
            'cooperation deepening under pressure is the pattern, and it hardens '
            'Tehran\'s read of the hub\'s alignment.'),
        'saudi_fingerprint': (
            '\U0001f1f8\U0001f1e6 Saudi wheel active -- Gulf-rival amplification',
            'The Saudi tracker\'s crosstheater fingerprint is live. Riyadh and Abu '
            'Dhabi run as partners on security and as rivals on OPEC+ quota, ports, '
            'and regional headquarters policy. Elevated Saudi activity is read here '
            'as competitive context for the economic_hub vector, not as a shared '
            'posture.'),
    }
    short, long = prose.get(amp_label, (
        f'\U0001f6de Sibling-wheel fingerprint active: {amp_label}',
        f'A sibling tracker fingerprint ({amp_label}) is live -- crosstheater amplification on the contested node.'))
    return {
        'level': 'elevated', 'type': 'crosstheater', 'priority': 6,
        'category': 'crosstheater', 'theatre': 'uae',
        'pressure_type': 'diplomatic',
        'short_text': short, 'long_text': long,
    }
def build_executive_summary(actor_summaries, vector_scores, vector_levels, tripwires_global):
    asum = actor_summaries or {}
    lv   = vector_levels or {}
    esc  = ('elevated', 'high', 'surge')
    hot_vecs = [VECTOR_NAMES.get(v, v) for v, l in lv.items() if l in esc]
    hot_actors = [ACTOR_PROSE_NAMES.get(a, a) for a, d in asum.items()
                  if isinstance(d, dict) and d.get('level') in ('high', 'surge')]
    tw_ids = [tw.get('id') for tw in (tripwires_global or []) if isinstance(tw, dict)]
    parts = []
    if tw_ids:
        parts.append("Tripwire(s) fired this scan: " + ", ".join(t.replace('_', ' ') for t in tw_ids[:3]) +
                     " -- see Top Signals for the read.")
    if hot_vecs:
        parts.append("Active vectors: " + ", ".join(hot_vecs).lower() +
                     (" -- driven by " + ", ".join(hot_actors[:3]) + "." if hot_actors else "."))
    else:
        parts.append("All four vectors at baseline.")
    _kin = (asum.get('uae_mod_airdefense') or {}).get('level', 'low')
    _com = (asum.get('dp_world_ports') or {}).get('level', 'low')
    if _kin in ('high', 'surge') and _com not in esc:
        parts.append("Kinetic tempo is running while the commercial lifeline holds -- the divergence "
                     "pattern that has historically read as contained. The dual-track balance axis "
                     "carries the measured read.")
    else:
        parts.append("Aligned-hub node: Israel axis + dual-polarity Iran spoke -- divergence between "
                     "kinetic and commercial tracks is the tell. Convergence read, not prediction.")
    return " ".join(parts)


def score_alignment_drift(actor_summaries, tripwires_global,
                          commodity_pressure, crosstheater_amplifiers,
                          country='uae', profile=None):
    """The UAE DUAL-TRACK BALANCE AXIS: is friction outpacing the lifeline?

    Nets friction pressure (kinetic threats, intercepts, trade-rupture
    signals) against the commercial lifeline (Dubai re-export trade, flights,
    diaspora finance). Bands, calm to hot:
        Lifeline-Dominant -> Mixed -> Friction-Rising -> Friction-Dominant
    Emits id dualtrack_axis_<country>. CONVERGENCE, not prediction.

    v1.1.0: this docstring used to describe the BRI tracker this file was
    cloned from -- "challenger (China/BRI) ... US-anchored -> Contested ->
    Drifting -> Realigning", and a promised id of bri_inroad_<country>. Not
    one of those bands or ids exists in this module. That stale ladder is
    where the dead 'US-anchored' calm guard came from, so this was not a
    cosmetic error: a wrong comment propagated into working code.
    """
    prof = profile or DRIFT_PROFILES.get((country or '').lower())
    if not prof:
        return None

    asum = actor_summaries or {}
    inroad_lvl  = _DRIFT_LEVEL_RANK.get((asum.get(prof['inroad_actor'])  or {}).get('level', 'low'), 0)
    counter_lvl = _DRIFT_LEVEL_RANK.get((asum.get(prof['counter_actor']) or {}).get('level', 'low'), 0)

    tw_ids = {tw.get('id') for tw in (tripwires_global or [])}
    inroad_tw  = [t for t in prof['inroad_tripwires']  if t in tw_ids]
    counter_tw = [t for t in prof['counter_tripwires'] if t in tw_ids]

    # structural dependency lever: standing baseline (operational megaport) OR a live commodity surge
    dep_active = bool(prof.get('structural_dependency_baseline', False))
    if not dep_active:
        for ck in prof.get('commodity_keys', ()):
            cp = (commodity_pressure or {}).get(ck) or {}
            if isinstance(cp, dict) and (cp.get('active') or cp.get('level') in ('elevated', 'high', 'surge')):
                dep_active = True
                break

    # v1.2.3 Oct 18 2026: was presence-only (any dict = active). Now the same
    # lit threshold the top-signal gate uses -- level >= 2. Iran is live at
    # 2-3, so no reading changes today; absence can no longer count as pressure.
    _amp = (crosstheater_amplifiers or {}).get(prof.get('crosstheater_amp', '')) or {}
    _amp_lvl = _amp.get('level') if isinstance(_amp, dict) else None
    amp_active = (isinstance(_amp_lvl, (int, float)) and _amp_lvl >= 2) or bool(_amp.get('active'))

    inroad  = inroad_lvl + len(inroad_tw) + (1 if dep_active else 0) + (1 if amp_active else 0)
    counter = counter_lvl + len(counter_tw)

    # ── band the NET drift ──
    if inroad <= 1:
        band = 'Lifeline-Dominant'
    elif inroad >= 2 and counter >= 2:
        band = 'Mixed'
    elif inroad >= 5 and counter <= 1 and dep_active:
        band = 'Friction-Dominant'
    elif (inroad - counter) >= 2:
        band = 'Friction-Rising'
    elif counter >= 2:
        band = 'Mixed'
    else:
        band = 'Lifeline-Dominant'

    # structural-dependency floor: an entrenched, operational inroad means the
    # alignment has already structurally landed -- at minimum 'Drifting'.
    if prof.get('structural_dependency_baseline') and band == 'Lifeline-Dominant':
        band = 'Friction-Rising'

    ip = prof['inroad_power']; cp_ = prof['incumbent_power']; cc = 'UAE'
    if band == 'Lifeline-Dominant':
        so_what = ("Friction signals read as routine posture noise against a healthy commercial "
                   "lifeline; the dual-track balance sits at its historical default -- Dubai commerce "
                   "absorbing whatever the kinetic weather brings.")
    elif band == 'Mixed':
        so_what = ("Friction pressure and lifeline anchors are both active -- both tracks running hot "
                   "simultaneously, consistent with " + prof['precedents'] + ". The balance is being "
                   "tested, not tipped.")
    elif band == 'Friction-Rising':
        so_what = ("Friction signals are outpacing the commercial lifeline; the pattern is consistent "
                   "with the kinetic track starting to drive the relationship -- watch trade/flight "
                   "vocabulary for the confirmation-via-commerce tell.")
    else:  # Friction-Dominant
        so_what = ("Sustained friction pressure with the commercial lifeline failing is consistent with "
                   "the pre-rupture pattern: kinetics and commerce breaking in the same window is the "
                   "combination that has historically preceded broader break.")
    disclaimer = ("This is a CONVERGENCE indicator on the lifeline-to-friction balance axis, NOT a "
                  "prediction of rupture. It measures whether friction signals are outpacing the "
                  "commercial lifeline; Abu Dhabi retains full agency over both tracks.")

    meta = DRIFT_BAND_META[band]
    return {
        'id':                'dualtrack_axis_' + (country or '').lower(),
        'country':           (country or '').lower(),
        'flag':              prof.get('flag', ''),
        'axis_label':        prof.get('axis_label', 'dual-track balance'),
        'band':              band,
        'inroad_power':      ip,
        'incumbent_power':   cp_,
        'inroad_score':      inroad,
        'counter_score':     counter,
        'net':               inroad - counter,
        'active_inroad_tripwires':  inroad_tw,
        'active_counter_tripwires': counter_tw,
        'dependency_active': dep_active,
        'regional_amp_active': amp_active,
        'so_what_factor':    so_what,
        'leading_indicators': list(prof['leading_indicators']),
        'precedent':         prof['precedents'],
        'disclaimer':        disclaimer,
        'level':             meta['level'],
        'priority':          meta['priority'],
        'color':             meta['color'],
        'icon':              '\U0001F9ED',       # compass
    }


def build_alignment_drift_top_signal(drift):
    """Canonical-schema top_signal for the dual-track balance read -> ME BLUF / GPI.

    Returns None on the CALM band, so a quiet cycle stays quiet.

    ── v1.1.0 Oct 11 2026: THIS GUARD WAS DEAD ──────────────────────────
    It tested for band 'US-anchored'. This module's bands are
    Lifeline-Dominant / Mixed / Friction-Rising / Friction-Dominant --
    'US-anchored' is not among them and never was; it is a band name from the
    BRI-drift tracker this file was cloned from (see the old
    score_alignment_drift docstring, which still described that ladder). So
    the guard could never match, and a dead-calm scan -- every actor at 'low',
    band 'Lifeline-Dominant' -- emitted a signal to the regional BLUF and the
    GPI EVERY SINGLE CYCLE. The BLUF could not tell a finding from a heartbeat.

    The calm band here is LIFELINE-DOMINANT: commercial lifeline healthy,
    friction routine. That is the baseline, and a baseline is not news.
    """
    if not drift or drift.get('band') in (None, AXIS_CALM_BAND):
        return None
    return {
        'priority':   drift['priority'],
        'category':   'alignment_drift',
        'theatre':    drift['country'],
        'level':      drift['level'],
        'icon':       drift['icon'],
        'color':      drift['color'],
        # v1.1.0: short_text spliced in `inroad_power`, which is a full
        # explanatory clause, producing "UAE: the friction track (kinetic
        # threats, intercepts, trade-rupture pressure) alignment drift --
        # Mixed". Short text has a 120-char budget and a job.
        'short_text': (drift['flag'] + ' ' + drift['country'].replace('_', ' ').upper() + ': ' +
                       drift.get('axis_label', 'dual-track balance') +
                       ' -- ' + drift['band']),
        'long_text':  ((drift['so_what_factor'] + ' ' + drift['disclaimer'])[:480]),
    }


def build_so_what_factor(actor_summaries, vector_scores, vector_levels, tripwires_global, commodity_pressure, alignment_drift=None):
    """Dynamic So-What bullets: implication chains, actor-aware, tripwire-aware.
    Returns [{bullet, weight}] highest weight first. Estimative voice."""
    bullets = []
    asum = actor_summaries or {}
    lv = vector_levels or {}
    esc = ('elevated', 'high', 'surge')

    def _drivers(vec):
        names = [ACTOR_PROSE_NAMES.get(a, a) for a in VECTOR_MEMBERS.get(vec, ())
                 if (asum.get(a) or {}).get('level') in esc]
        return (" Driving this scan: " + ", ".join(names) + ".") if names else ""

    CHAINS = {
        'kinetic_inbound': ("Kinetic-inbound at {lvl}. What it means: intercept/threat tempo at this level "
            "reads against the Jan 2022 Abu Dhabi precedent -- strikes on UAE soil historically reprice "
            "aviation routings, tourism risk, and war-risk premiums at Fujairah within days. Who feels it: "
            "Gulf carriers, hull insurers, Dubai's services economy. Confirmation gauges: activation "
            "reporting, Fujairah advisories, the DFM/ADX tiles.", 0.95),
        'israel_axis': ("Israel-axis at {lvl}. What it means: defense-cooperation tempo (EDGE-Rafael, "
            "transfers, training) is the Accords-goes-kinetic story deepening -- integrating Gulf air defense "
            "with Israeli systems and repricing the regional deterrence read. Who feels it: Tehran's targeting "
            "calculus, Gulf procurement, the normalization file region-wide. Confirmation gauges: deal "
            "announcements, joint exercises, the MIL israel_uae_defense amplifier.", 0.9),
        'iran_dual': ("Iran dual-track at {lvl}. What it means: friction and lifeline run simultaneously -- "
            "the question is WHICH drives the tempo. Lifeline holding while kinetics spike has historically "
            "read as contained; commercial rupture alongside kinetic escalation is confirmation-via-commerce. "
            "The balance axis above carries the measured read. Confirmation gauges: flight schedules, trade "
            "volumes, divergence between story counts.", 0.9),
        'economic_hub': ("Economic-hub at {lvl}. What it means: Jebel Ali is the region's largest port on a "
            "six-continent DP World network -- disruption transmits into global logistics costs, not just Gulf "
            "ones; DMCC gold flows double as sanctions weather. Who feels it: global shippers, gold markets, "
            "ADNOC buyers. Confirmation gauges: war-risk premiums, operations statements, the Gold x Transit "
            "Hub card.", 0.85),
    }
    for vec, (txt, w) in CHAINS.items():
        l = lv.get(vec)
        if l in esc:
            bullets.append({'weight': w, 'bullet': txt.format(lvl=str(l).upper()) + _drivers(vec)})

    # tripwire-aware bullets (highest weight -- events outrank tempo)
    for tw in (tripwires_global or [])[:2]:
        if isinstance(tw, dict) and tw.get('id'):
            bullets.append({'weight': 0.98, 'bullet':
                "Tripwire -- " + str(tw['id']).replace('_', ' ') + ": " + _tripwire_prose(tw['id'], None)})

    # drift lead: rendered as its own block by the frontend, but add the axis bullet when moving
    if alignment_drift and alignment_drift.get('band') not in (None, 'Lifeline-Dominant'):
        bullets.append({'weight': 0.92, 'bullet':
            "Dual-track balance reads " + alignment_drift['band'] + ": " +
            (alignment_drift.get('so_what_factor') or '')})

    if not bullets:
        bullets.append({'weight': 0.3, 'bullet':
            "All four vectors at baseline this scan. Baseline for the aligned hub still means both Iran "
            "tracks running simultaneously -- friction and lifeline -- and the Israel defense axis "
            "compounding quietly. Divergence between kinetic and commercial rhetoric remains the standing tell."})
    bullets.sort(key=lambda b: -b['weight'])
    return bullets[:6]

def interpret_uae_signals(scan_data):
    """
    Convenience wrapper — accepts a complete scan_data dict and returns the
    four derived analytical fields (it returns four, not three: top_signals,
    executive_summary, so_what, alignment_drift).
    """
    actor_summaries        = scan_data.get('actor_summaries', {}) or {}
    vector_scores          = scan_data.get('vector_scores', {}) or {}
    vector_levels          = scan_data.get('vector_levels', {}) or {}
    tripwires_global       = scan_data.get('tripwires_global', []) or []
    commodity_pressure     = scan_data.get('commodity_pressure', {}) or {}
    crosstheater_amplifiers = scan_data.get('crosstheater_amplifiers', {}) or {}

    drift = score_alignment_drift(actor_summaries, tripwires_global,
                                  commodity_pressure, crosstheater_amplifiers,
                                  country='uae')
    return {
        'top_signals':       build_top_signals(actor_summaries, tripwires_global,
                                                commodity_pressure, crosstheater_amplifiers),
        'executive_summary': build_executive_summary(actor_summaries, vector_scores,
                                                     vector_levels, tripwires_global),
        'so_what':           build_so_what_factor(actor_summaries, vector_scores, vector_levels,
                                                   tripwires_global, commodity_pressure,
                                                   alignment_drift=drift),
        'alignment_drift':   drift,
    }


# ── Module constants sit BELOW the functions that read them. That is fine at
# runtime (they resolve at call time) but it meant the "Module loaded" banner
# printed from the MIDDLE of the file, before DRIFT_BAND_META existed. Moved
# to the true end of file.
DRIFT_BAND_META = {
    'Lifeline-Dominant': {'level': 1, 'color': '#22c55e', 'priority': 8},
    'Mixed':             {'level': 3, 'color': '#f59e0b', 'priority': 12},
    'Friction-Rising':   {'level': 4, 'color': '#f97316', 'priority': 13},
    'Friction-Dominant': {'level': 5, 'color': '#dc2626', 'priority': 14},
}

# The calm band, named ONCE. build_alignment_drift_top_signal returns None on
# it, and that return is the only thing between a quiet cycle and a signal
# broadcast to the GPI.
AXIS_CALM_BAND = 'Lifeline-Dominant'

# Structural guard. The old guard referenced a band absent from the table
# above, and nothing caught it for three months because a guard that never
# fires looks exactly like a guard that is never needed. Name a calm band that
# is not real and this module now refuses to load.
assert AXIS_CALM_BAND in DRIFT_BAND_META, (
    "AXIS_CALM_BAND must name a real band in DRIFT_BAND_META, or the calm "
    "guard in build_alignment_drift_top_signal can never return None and the "
    "dual-track axis broadcasts on every scan, including dead-calm ones.")

DRIFT_PROFILES = {
    'uae': {
        'flag':            '\U0001F1E6\U0001F1EA',
        'axis_label':      'dual-track balance',   # short form, for short_text
        'inroad_power':    'the friction track (kinetic threats, intercepts, trade-rupture pressure)',
        'incumbent_power': 'the commercial lifeline (Dubai re-export trade, flights, diaspora finance)',
        'inroad_actor':    'uae_mod_airdefense',
        'counter_actor':   'dp_world_ports',
        'inroad_tripwires':  ('homeland_attack', 'iran_trade_rupture', 'fujairah_maritime_incident'),
        'counter_tripwires': (),
        'dependency_channel': "Dubai's role as Iran's historical trade lung -- the commercial channel that has absorbed kinetic shocks across every prior cycle",
        'commodity_keys':     ('gold', 'oil'),
        'crosstheater_amp':   'iran_fingerprint',
        'structural_dependency_baseline': False,
        'precedents': ("the Jan 2022 Abu Dhabi strikes (kinetics spiked, Dubai-Iran commerce held, the "
                       "cycle contained) and the 2019 Fujairah incidents (maritime friction absorbed "
                       "without commercial rupture)"),
        'leading_indicators': [
            'Intercept-announcement cadence (the friction track made legible)',
            'Iran-UAE flight schedules and re-export volume vocabulary (lifeline health)',
            'Fujairah anchorage advisories and war-risk premium reporting',
            'Divergence between kinetic and commercial story counts (the tell itself)',
            'DMCC gold-flow vocabulary (sanctions-pressure weather on the lifeline)',
        ],
    },
}

_DRIFT_LEVEL_RANK = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}



print("[UAE Signal Interpreter] Module loaded -- v%s" % MODULE_VERSION)
