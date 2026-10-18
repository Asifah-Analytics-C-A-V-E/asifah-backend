"""
saudi_arabia_signal_interpreter.py -- Asifah Analytics ME Backend -- v1.0.0 Jul 2026
Analyst layer for rhetoric_tracker_saudi_arabia (friction tier + detente shim).
5-function contract: build_top_signals / build_executive_summary /
build_so_what_factor / score_alignment_drift / build_alignment_drift_top_signal.
DRIFT AXIS: the ACCORDS AXIS -- holdout <-> signature. Bands:
Holdout -> Warming -> Converging -> Signature-Track. Nets normalization-inroad
pressure (Accords signals, US package, detente rupture as accelerant) against
holdout anchors (Palestinian-file preconditions, Iran-detente hedge).
Estimative voice. Convergence, not prediction. The reader completes the inference.
"""

# ============================================
# CONFIGURATION
# ============================================
# v1.1.0: `import re` and `from datetime import ...` removed -- neither name
# was referenced anywhere in this module.

MODULE_VERSION = '1.3.1'

LEVEL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']
ESCALATORY_LEVELS = {'elevated', 'high', 'surge'}

# Vector display names for prose
VECTOR_NAMES = {
    'kinetic_inbound':         'Kinetic Inbound',
    'energy_infrastructure':   'Energy Infrastructure',
    'normalization_watch':     'Normalization Watch',
    'domestic_transformation': 'Domestic Transformation',
    'guarantor_response':      'Guarantor Response',
}

VECTOR_MEMBERS = {
    'kinetic_inbound':         ('houthi_yemen', 'saudi_mod_airdefense', 'iran_saudi'),
    'energy_infrastructure':   ('aramco_energy', 'opec_policy'),
    'normalization_watch':     ('accords_normalization', 'us_saudi', 'gcc_saudi'),
    'domestic_transformation': ('royal_court_mbs', 'vision2030_domestic'),
    # v1.3.0: the two vectors/actors added 11 + 18 Oct had no members here, so
    # so-what "Driving this scan" never named them.
    'guarantor_response':      ('mecca_pact_turkiye', 'mecca_pact_pakistan', 'egypt_support'),
}

TRIPWIRE_LABELS = {
    'non_pact_deployment':     'Non-Pact Deployment (Egypt)',
    'israel_defense_transfer': 'Israeli Defence Transfer',
    'hormuz_closure':          'Hormuz Closure',
    'hajj_mass_casualty':      'Hajj Mass Casualty',
}

# Actor display names for prose (cleaner than the formal `name` field)
ACTOR_PROSE_NAMES = {
    'royal_court_mbs':       'the Royal Court / MBS',
    'vision2030_domestic':   'the Vision 2030 track',
    'saudi_mod_airdefense':  'Saudi MOD / air defense',
    'aramco_energy':         'Aramco / energy infrastructure',
    'opec_policy':           'the OPEC+ policy voice',
    'houthi_yemen':          'the Houthi / Yemen front',
    'iran_saudi':            'the Iran file (friction + detente)',
    'accords_normalization': 'the Israel normalization watch',
    'us_saudi':              'the US-Saudi track',
    'gcc_saudi':             'the GCC posture line',
    'palestinian_file':      'the Palestinian file (holdout anchors)',
    'mecca_pact_turkiye':    'Turkiye (Mecca Pact guarantor)',
    'mecca_pact_pakistan':   'Pakistan (Mecca Pact guarantor)',
    'egypt_support':         'Egypt (non-pact support)',
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
                       + ' across ' + esc_txt + '. Saudi Arabia supply-risk premium is '
                       'partly a political risk premium -- read this composite against '
                       'the rhetoric vectors, which are scored on the same window.'),
        'source_link': '/saudi_arabia-stability.html#commodities',
    }


def build_top_signals(actor_summaries, tripwires_global, commodity_pressure, crosstheater_amplifiers):
    """
    Build the canonical top_signals[] array for the Saudi Arabia rhetoric tracker.

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
        short = "\u26a0 Tripwire: " + (TRIPWIRE_LABELS.get(tw_id) or str(tw_id).replace('_', ' ').title())
        # v1.2.2: carry the tripwire id + confirmation class to the page. The
        # same tripwire can fire under several actors with different classes
        # (live: succession_event confirmed under one actor, claim_sourced
        # under another) -- aggregate: confirmed if ANY entry is confirmed.
        _same = [t for t in (tripwires_global or []) if t.get('id') == tw_id]
        _conf = ('confirmed' if any(t.get('confirmation') == 'confirmed' for t in _same)
                 else next((t.get('confirmation') for t in _same if t.get('confirmation')), None))
        _chans = sorted({c for t in _same for c in (t.get('claim_channels') or [])})
        signals.append({
            'short_text': short,
            'long_text':  long_text,
            'level':      tw.get('severity', 'high'),
            'type':       'tripwire',
            'actor':      actor_id,
            'sources':    sources,
            'tripwire_id':    tw_id,
            'confirmation':   _conf,                       # confirmed | claim_sourced | None (RSS-only path)
            'confirmed_by':   sum(int(t.get('confirmed_by') or 0) for t in _same),
            'claim_channels': _chans[:6],
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
        # v1.2.0: ported from UAE v1.1.0. The gate was `active` alone; canonical
        # crosstheater fingerprints carry a numeric `level` and often no
        # 'active' key (live 18 Oct: iran_fingerprint level 2, active None --
        # dropped). Accept either, at the platform's lit threshold of 2.
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
    """Per-tripwire estimative prose. Pattern-level, precedent-anchored."""
    P = {
        'infrastructure_strike': (
            "Abqaiq-class energy-infrastructure strike signals detected. The 2019 precedent halved "
            "Saudi output in a single day and repriced Brent within hours -- facility-attack reporting "
            "at tripwire confidence is the platform's highest-weight Saudi energy signal. Watch Aramco "
            "operational statements and Petroline/Yanbu bypass activation as the recovery tells."),
        'houthi_salvo': (
            "Kinetic salvo on Saudi territory at tripwire confidence. Salvo events have historically "
            "arrived in cycles, not singletons -- the 72-hour window after a confirmed strike carries "
            "elevated repeat probability by precedent. Watch intercept-announcement cadence and "
            "southern-airport advisories."),
        'hormuz_closure': (
            "Hormuz-closure vocabulary at tripwire confidence. For Riyadh this activates the bypass "
            "story: the East-West Petroline to Yanbu caps the scenario at roughly 5M bpd of re-routable "
            "crude -- the infrastructure Riyadh built for exactly this headline. Global crude repricing "
            "is the by-construction consequence."),
        'accords_signature': (
            "Signature-event vocabulary on the Saudi-Israel file at tripwire confidence. This is THE "
            "drift-axis crossing: a signed deal would reprice regional defense architecture, Israeli "
            "market access, and the Palestinian file simultaneously. De-escalatory for the region's "
            "kinetic picture; seismic for its map."),
        'succession_event': (
            "Royal-succession vocabulary at tripwire confidence. Succession is the domestic-"
            "transformation vector's maximum-weight event class -- historically the moment when every "
            "external file (Mecca Pact, Accords, US pact) gets re-anchored at once. Watch allegiance-"
            "council reporting and decree tempo."),
        'detente_rupture': (
            "Detente-rupture vocabulary at tripwire confidence. The Beijing-2023 normalization track is "
            "the friction tier's brake -- rupture removes it. Historically, friction spikes WITHOUT the "
            "detente channel have escalated further than identical spikes with the channel intact. This "
            "also accelerates the Accords drift axis: losing the Iran hedge strengthens the US-Israel "
            "security logic."),
        'israel_defense_transfer': (
            "Israeli defense-cooperation vocabulary on the Saudi file at tripwire confidence. This is the "
            "one forcing path on the Accords axis: Riyadh's stated holdout is anchored by Gaza, the West "
            "Bank and Lebanon, and only a defense need acute enough to outweigh that file moves it. The "
            "tell is Riyadh's response -- a public denial keeps the holdout intact; silence is the signal. "
            "US-sourced claims of cooperation are not Saudi confirmation."),
        'non_pact_deployment': (
            "A non-signatory's forces arriving in the Kingdom, at tripwire confidence. Egypt is not in the "
            "Mecca Pact; its deployment answers the pact's own question -- does an attack on Saudi Arabia "
            "pull in third parties -- from OUTSIDE the treaty. Read it against Turkiye and Pakistan: if the "
            "outsider arrives before the guarantors move, the pact is being priced by its absence."),
        'hajj_mass_casualty': (
            "Hajj mass-casualty signals at tripwire confidence -- a Custodian-legitimacy event class. "
            "NOTE: Hajj-window timing itself is a calendar MULTIPLIER on other tripwires, never a "
            "standalone signal (Black Swan doctrine); this tripwire fires only on actual casualty/attack "
            "reporting."),
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
        "Convergence is more analytically significant than any individual vector — when "
        "domestic-stability pressure intersects with resource-sector or alignment vectors, "
        "Saudi Arabia's risk profile compounds across normally-independent dimensions."
    )
    # v1.1.0: was `' '.join(...) if False else '\n'.join(...)` -- a ternary
    # with a constant-false test, i.e. a dead branch pretending to be a choice.
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
    """Per-actor estimative prose for actor_signal long_text."""
    lvl = (actor or {}).get('level', 'low')
    de  = " De-escalatory vocabulary is present in the same window -- read the tempo against it." if deescalation else ""
    P = {
        'royal_court_mbs':
            "Royal Court / MBS statement tempo at " + lvl + " -- the Gulf's heaviest leader-signal source. "
            "Elevated tempo here has historically preceded policy pivots announced by decree rather than "
            "process: watch for foreign-policy declarations, succession-adjacent language, and PIF "
            "direction shifts riding the same cycle.",
        'vision2030_domestic':
            "Vision 2030 signal volume at " + lvl + ". Re-scoping, delay, and budget vocabulary at this "
            "tempo reads as fiscal pressure; PIF deployment shifts transmit into global asset markets "
            "within quarters. Giga-project milestone slippage is the leading indicator.",
        'saudi_mod_airdefense':
            "Saudi MOD / air-defense tempo at " + lvl + ". Intercept-announcement surges track inbound-"
            "threat cycles almost one-to-one -- the announcements themselves are the sensor. Procurement "
            "and exercise vocabulary in the same window reads as posture-hardening.",
        'aramco_energy':
            "Aramco / energy-infrastructure signal volume at " + lvl + ". Facility, pipeline, and "
            "throughput reporting at this tempo is the platform's most market-coupled Saudi read -- "
            "Brent absorbs this vector within days when sustained. Petroline/Yanbu and IMEC corridor "
            "signals ride here.",
        'opec_policy':
            "OPEC+ policy voice at " + lvl + ". Production-policy rhetoric surges have historically "
            "preceded quota decisions that move Brent; ministerial-meeting vocabulary plus voluntary-cut "
            "language is the pre-decision fingerprint. Watch the Riyadh-Abu Dhabi quota friction line.",
        'houthi_yemen':
            "Houthi / Yemen-front tempo at " + lvl + " toward Saudi targets. The 2019-2022 strike record "
            "(Abqaiq, Jeddah, Abha) is the precedent set; claim tempo plus named-target specificity "
            "moving together is the pre-strike pattern. Truce-status vocabulary is the counterweight to "
            "read against.",
        'iran_saudi':
            "Iran-file tempo at " + lvl + " on the friction-with-detente-shim tier. The analyst question "
            "is which vocabulary dominates: threat/incident language (friction) or embassy/hajj/trade "
            "language (the Beijing-2023 track). Friction spikes with the detente channel intact have "
            "historically stayed contained -- the detente_rupture tripwire is the brake-failure tell.",
        'accords_normalization':
            "Israel-normalization watch at " + lvl + ". Each signature-language cycle moves the "
            "holdout-to-signature drift axis; precondition vocabulary (Palestinian-state language) is "
            "the counterweight that re-anchors holdout. This actor feeds the Accords drift axis directly.",
        'us_saudi':
            "US-Saudi track at " + lvl + ". Defense-pact, arms-package, and security-guarantee vocabulary "
            "at this tempo couples directly to the normalization file -- the US package IS the signature "
            "path's price. Presidential-visit and pact-milestone reporting are the tells.",
        'gcc_saudi':
            "GCC posture line at " + lvl + ". Riyadh's cohesion/rift vocabulary reads against the 2017 "
            "blockade precedent -- rift language from the GCC's anchor member is never noise. Summit "
            "outcomes and bilateral normalization gestures are the confirmation gauges.",
        # v1.3.0: these four fell through to the generic line ("Actor signal
        # tempo at elevated versus baseline") -- live for Pakistan on 18 Oct.
        'palestinian_file':
            "Palestinian-file tempo at " + lvl + " -- the holdout anchors Riyadh actually names (Gaza, the "
            "West Bank, Lebanon). Hardening language here re-anchors the Accords holdout; softening or "
            "SILENCE while the normalization track is active is the signature-adjacent tell.",
        'mecca_pact_turkiye':
            "Turkiye guarantor tempo at " + lvl + ". Ankara is a Mecca Pact guarantor AND a hub on this "
            "platform -- deployment, basing or overflight vocabulary here also lights the Turkey wheel's "
            "Saudi spoke. Words usually move before forces; watch whether they do.",
        'mecca_pact_pakistan':
            "Pakistan guarantor tempo at " + lvl + ". DG ISPR is the authoritative voice and it speaks in "
            "Urdu first. Islamabad has already said troops are present in the Kingdom under the pact; "
            "tempo here measures whether that presence is being publicly re-committed under fire.",
        'egypt_support':
            "Egyptian support tempo at " + lvl + " -- a NON-signatory. Cairo moving (defence-council "
            "approval, transport aircraft at Taif, parliamentary authorisation for troops) while the pact "
            "guarantors stay flat is the comparison that matters: an outsider responding first re-prices "
            "what the pact is worth. The Houthis have warned Cairo directly -- watch Red Sea / Suez "
            "exposure as the cost Egypt is accepting.",
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
    long_text = (
        f"The commodity tracker is reporting {alert}-level pressure on Saudi Arabia's {commodity_id} "
        f"sector (Saudi Arabia is a {role}{rank_str}). {sig_count} cross-tracker signals flagged. "
        f"This is a coupling event: the energy_infrastructure vector -- Aramco facilities, "
        f"the Petroline/Yanbu bypass, Ras Tanura throughput -- is where Saudi rhetoric meets "
        f"{commodity_id} supply, and the Kingdom's supply-risk premium is partly a political "
        f"risk premium. Watch for sector-rhetoric and price-impact alignment."
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
        # v1.1.0: was hardcoded 'drug_economy' -- not an actor in this file.
        'actor':      None,
        'sources':    sources,
    }


def _crosstheater_signal(amp_label, amp_data):
    """Signal for an active sibling-wheel fingerprint (absence-honest: only called when present)."""
    # v1.1.0 -- REALIGNED TO WHAT THE TRACKER ACTUALLY READS.
    # rhetoric_tracker_saudi_arabia._read_crosstheater_amplifiers() fetches
    # exactly three keys: iran_fingerprint, israel_fingerprint,
    # yemen_fingerprint. The old table had prose for pakistan and china --
    # neither is fetched, so neither could ever render -- and NONE for israel
    # or yemen, the two that matter most this month. The china entry described
    # "extraction-track positioning in Kabul (Mes Aynak, Amu Darya)", which is
    # Afghanistan, in a Saudi file.
    #
    # Pakistan WOULD now be analytically live via the Mecca Pact. It is not
    # added here because the tracker does not fetch that key -- writing prose
    # for a feed nobody reads is how the last table got this way. If a
    # Pakistan fingerprint is wired in, add the entry then.
    prose = {
        'iran_fingerprint': (
            '\U0001f1ee\U0001f1f7 Iran wheel active -- friction-side amplification',
            'The Iran tracker\'s crosstheater fingerprint is live. With the detente '
            'shim no longer load-bearing, elevated Iranian theatre pressure now '
            'transmits to Riyadh through the Houthi file rather than through the '
            'bilateral channel -- watch kinetic_inbound and guarantor_response '
            'together, not the Iran actor alone.'),
        'israel_fingerprint': (
            '\U0001f1ee\U0001f1f1 Israel wheel active -- Accords-axis context (cuts both ways)',
            'The Israel tracker\'s crosstheater fingerprint is live. This cuts BOTH '
            'ways on the Accords axis and the direction is the whole question: '
            'Israeli operations in Gaza, the West Bank or Lebanon re-anchor Riyadh\'s '
            'holdout, while Israeli defence capability moving toward Riyadh under '
            'fire is the inroad path -- the UAE\'s road. Read which one is driving.'),
        'yemen_fingerprint': (
            '\U0001f1fe\U0001f1ea Yemen wheel active -- inbound-threat amplification',
            'The Yemen tracker\'s crosstheater fingerprint is live. Yemen-theatre '
            'pressure is the most direct amplifier on Saudi kinetic_inbound: the '
            'Oct 2026 Riyadh airport strikes are the current precedent set, and '
            'claim tempo plus named-target specificity moving together is the '
            'pre-strike pattern.'),
    }
    short, long = prose.get(amp_label, (
        f'\U0001f6de Sibling-wheel fingerprint active: {amp_label}',
        f'A sibling tracker fingerprint ({amp_label}) is live -- crosstheater amplification on the contested node.'))
    return {
        'level': 'elevated', 'type': 'crosstheater', 'priority': 6,
        'category': 'crosstheater', 'theatre': 'saudi_arabia',
        'pressure_type': 'diplomatic',
        'short_text': short, 'long_text': long,
    }
def build_executive_summary(actor_summaries, vector_scores, vector_levels, tripwires_global):
    """1-3 sentence analyst BLUF. Estimative voice, precedent-anchored."""
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
                     " -- low-base-rate, high-impact event class; see Top Signals for the read.")
    if hot_vecs:
        parts.append("Active vectors: " + ", ".join(hot_vecs).lower() +
                     (" -- driven by " + ", ".join(hot_actors[:3]) + "." if hot_actors else "."))
    else:
        parts.append("All four vectors at baseline.")
    # standing frame
    _iran = (asum.get('iran_saudi') or {}).get('level', 'low')
    _norm = (asum.get('accords_normalization') or {}).get('level', 'low')
    if _iran in esc and _norm in esc:
        parts.append("Friction and normalization signals are running simultaneously -- the dual-hedge "
                     "pattern: Riyadh pricing both the Iran detente and the Israel signature path in the "
                     "same window.")
    else:
        parts.append("Friction-tier node with detente shim: Iran friction reads against the Beijing-2023 "
                     "track; the Accords drift axis stays live. Convergence read, not prediction.")
    return " ".join(parts)


def score_alignment_drift(actor_summaries, tripwires_global,
                          commodity_pressure, crosstheater_amplifiers,
                          country='saudi_arabia', profile=None):
    """The SAUDI ACCORDS AXIS: is the signature track outpacing the holdout?

    Nets normalization-inroad pressure against the anchors Riyadh actually
    names. Bands, calm to hot:
        Holdout -> Warming -> Converging -> Signature-Track
    Emits id accords_axis_<country>. CONVERGENCE, not prediction.

    v1.1.0: the docstring used to describe the BRI tracker this was cloned
    from -- "challenger (China/BRI) ... US-anchored -> Contested -> Drifting
    -> Realigning", id bri_inroad_<country>. None of those bands or that id
    exist here, and that stale ladder is where the dead 'US-anchored' calm
    guard came from. A wrong comment propagated into working code.
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

    _amp = (crosstheater_amplifiers or {}).get(prof.get('crosstheater_amp', '')) or {}
    _amp_lvl = _amp.get('level') if isinstance(_amp, dict) else None
    amp_active = isinstance(_amp_lvl, (int, float)) and _amp_lvl >= 2

    # v1.3.1 Oct 18 2026 -- ISRAEL'S WAR TEMPO IS CONTEXT, NOT SIGNATURE PRESSURE.
    # v1 added +1 to the inroad side whenever the Israel fingerprint merely
    # EXISTED. Harmless only while that fingerprint never arrived (it lives in
    # the collective dict, which the tracker did not read). Once connected, every
    # scan would carry a permanent +1 toward normalization because Israel is at
    # war. Per Rachel's 11 Oct ruling the inroad evidence is the normalization
    # track + the israel_defense_transfer forcing path; Israel's theatre level is
    # neither. It stays reported (regional_amp_active), not scored.
    inroad  = inroad_lvl + len(inroad_tw) + (1 if dep_active else 0)
    counter = counter_lvl + len(counter_tw)

    # ── band the NET drift ──
    if inroad <= 1:
        band = 'Holdout'
    elif inroad >= 2 and counter >= 2:
        band = 'Warming'
    elif inroad >= 5 and counter <= 1 and dep_active:
        band = 'Signature-Track'
    elif (inroad - counter) >= 2:
        band = 'Converging'
    elif counter >= 2:
        band = 'Warming'
    else:
        band = 'Holdout'

    # structural-dependency floor: an entrenched, operational inroad means the
    # alignment has already structurally landed -- at minimum 'Drifting'.
    if prof.get('structural_dependency_baseline') and band == 'Holdout':
        band = 'Converging'

    ip = prof['inroad_power']; cp_ = prof['incumbent_power']; cc = 'Saudi Arabia'
    if band == 'Holdout':
        so_what = ("Normalization signals read as routine diplomatic maintenance rather than a converging "
                   "signature pattern. Riyadh's stated anchors -- Gaza, the West Bank and Lebanon -- are "
                   "holding, and holdout is this axis's EXPECTED state, not a surprise. The reading that "
                   "would move it is not a summit but a capability transfer: Israeli air defence arriving "
                   "under fire, as it did for the UAE.")
    elif band == 'Warming':
        so_what = ("Signature-track signals and holdout anchors are both active -- a contested file "
                   "consistent with " + prof['precedents'] + ". The axis is being negotiated, not crossed.")
    elif band == 'Converging':
        so_what = ("Signature-track signals are outpacing the holdout anchors; with " +
                   prof['dependency_channel'] + " advancing, the pattern is consistent with movement "
                   "along the holdout-to-signature axis faster than preconditions are re-anchoring it.")
    else:  # Signature-Track
        so_what = ("Sustained signature-track signals, an advancing US package, and weakening holdout "
                   "anchors are consistent with the pattern that immediately preceded prior Accords "
                   "signatures. The axis crossing itself remains a sovereign decision -- this measures "
                   "convergence toward it, nothing more.")
    disclaimer = ("This is a CONVERGENCE indicator on the holdout-to-signature axis, NOT a "
                  "prediction of normalization. It measures whether signature-track signals are "
                  "outpacing holdout anchors; Riyadh retains full agency over the decision.")

    meta = DRIFT_BAND_META[band]
    return {
        'id':                'accords_axis_' + (country or '').lower(),
        'country':           (country or '').lower(),
        'flag':              prof.get('flag', ''),
        'axis_label':        prof.get('axis_label', 'Accords axis'),
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
    """Canonical-schema top_signal for the Accords axis -> ME BLUF / GPI.

    Returns None on the CALM band, so a quiet cycle stays quiet.

    ── v1.1.0 Oct 11 2026: THIS GUARD WAS DEAD ──────────────────────────
    It tested for band 'US-anchored'. This module's bands are Holdout /
    Warming / Converging / Signature-Track. 'US-anchored' is the band name
    from the BRI-drift tracker this file was cloned from, and the old
    score_alignment_drift docstring still described that ladder -- so the
    guard was written from a stale COMMENT rather than from the code.
    It could never match. A dead-calm scan (band 'Holdout') therefore
    broadcast an alignment_drift signal to the regional BLUF and the GPI on
    EVERY cycle. The BLUF could not tell a finding from a heartbeat.

    The calm band here is HOLDOUT. Saudi Arabia has not crossed this axis
    and, per Rachel's 11 Oct 2026 ruling, no crossing is judged imminent --
    so holdout IS the baseline, and a baseline is not news.
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
        # v1.1.0: this spliced in `inroad_power`, a full explanatory clause,
        # into a field with a 120-char budget.
        'short_text': (drift['flag'] + ' ' + drift['country'].replace('_', ' ').upper() + ': ' +
                       drift.get('axis_label', 'Accords axis') +
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
        'kinetic_inbound': ("Kinetic-inbound at {lvl}. What it means: strike-cycle tempo at this level has "
            "historically added a risk premium to Brent within the same week and repriced war-risk insurance "
            "on Gulf and Red Sea routings -- Abqaiq 2019 is the anchor precedent (one strike halved output in "
            "a day). Who feels it first: crude buyers, tanker insurers, air-defense procurement. Confirmation "
            "gauges: the Brent tile, intercept-announcement cadence, southern-airport advisories.", 0.95),
        'energy_infrastructure': ("Energy-infrastructure at {lvl}. What it means: facility/pipeline tempo "
            "transmits to Brent and product cracks within days when sustained; the East-West Petroline to "
            "Yanbu caps the Hormuz-closure scenario at roughly 5M bpd of re-routable crude. IMEC signals ride "
            "this vector as the counter-BRI corridor story. Confirmation gauges: Brent + Aramco tiles, "
            "Petroline throughput reporting.", 0.9),
        'normalization_watch': ("Normalization-watch at {lvl}. What it means: signature-language cycles at "
            "this tempo have historically moved the whole realignment picture -- a deal would reprice defense "
            "pacts, Israeli market access, and the Palestinian file simultaneously. The Accords axis card "
            "above carries the measured read. Confirmation gauges: US-package milestones, precondition "
            "language.", 0.85),
        'domestic_transformation': ("Domestic-transformation at {lvl}. What it means: decree and re-scoping "
            "tempo reads as fiscal pressure -- PIF is a mega-allocator, so deployment shifts transmit into "
            "global asset markets within quarters; succession signals ride this vector at maximum weight. "
            "Confirmation gauges: giga-project milestones, budget statements, the Tadawul tile.", 0.8),
        'guarantor_response': ("Guarantor & third-party response at {lvl}. What it means: an attack on "
            "the Kingdom is pulling in outside military support -- the question the Mecca Pact was built "
            "to answer. Who is moving matters more than how much: guarantor movement (Turkiye, Pakistan) "
            "tests the pact; non-signatory movement (Egypt) tests the region around it. The Mecca Pact "
            "card carries the measured reading. Confirmation gauges: deployment and basing statements, "
            "DG ISPR, transport-aircraft and air-defence arrivals.", 0.88),
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
    if alignment_drift and alignment_drift.get('band') not in (None, 'Holdout'):
        bullets.append({'weight': 0.92, 'bullet':
            "Accords axis reads " + alignment_drift['band'] + ": " +
            (alignment_drift.get('so_what_factor') or '')})

    if not bullets:
        bullets.append({'weight': 0.3, 'bullet':
            "All four vectors at baseline this scan. Baseline for a friction-tier node still means the "
            "detente shim is load-bearing and the Accords drift axis stays live. Quiet is a posture, not "
            "an absence."})
    bullets.sort(key=lambda b: -b['weight'])
    return bullets[:6]

def interpret_saudi_arabia_signals(scan_data):
    """
    Convenience wrapper — accepts a complete scan_data dict and returns the
    three derived analytical fields. Mirrors the Japan tracker's contract.
    """
    actor_summaries        = scan_data.get('actor_summaries', {}) or {}
    vector_scores          = scan_data.get('vector_scores', {}) or {}
    vector_levels          = scan_data.get('vector_levels', {}) or {}
    tripwires_global       = scan_data.get('tripwires_global', []) or []
    commodity_pressure     = scan_data.get('commodity_pressure', {}) or {}
    crosstheater_amplifiers = scan_data.get('crosstheater_amplifiers', {}) or {}

    drift = score_alignment_drift(actor_summaries, tripwires_global,
                                  commodity_pressure, crosstheater_amplifiers,
                                  country='saudi_arabia')
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


# Constants sit below the functions that read them (fine at runtime), but the
# load banner printed from the MIDDLE of the file. Moved to the true end.
DRIFT_BAND_META = {
    'Holdout':         {'level': 1, 'color': '#38bdf8', 'priority': 8},
    'Warming':         {'level': 3, 'color': '#f59e0b', 'priority': 12},
    'Converging':      {'level': 4, 'color': '#f97316', 'priority': 13},
    'Signature-Track': {'level': 5, 'color': '#dc2626', 'priority': 14},
}

# The calm band, named ONCE. build_alignment_drift_top_signal returns None on
# it, and that return is the only thing between a quiet cycle and a signal
# broadcast to the GPI.
AXIS_CALM_BAND = 'Holdout'

# Structural guard. The old guard named a band absent from the table above and
# nothing caught it for three months, because a guard that never fires looks
# exactly like a guard that is never needed.
assert AXIS_CALM_BAND in DRIFT_BAND_META, (
    "AXIS_CALM_BAND must name a real band in DRIFT_BAND_META, or the calm "
    "guard in build_alignment_drift_top_signal can never return None and the "
    "Accords axis broadcasts on every scan, including dead-calm ones.")

# ════════════════════════════════════════════════════════════
# RACHEL'S RULING, 11 OCT 2026 -- what changed in this profile
#
#   "By accords are we referencing the Abraham Accords, to which KSA is still
#    holding out -- we do want to keep it mentioned and tracked -- but I don't
#    necc see any change imminently, unless KSA needs some kind of defense/
#    weapons from Israel to a degree that it forces their hand - otherwise,
#    continue to track what's happening in Gaza, West Bank, and even Lebanon
#    as KSA's reasons to abstain from the Accords."
#
# Three consequences, all implemented below:
#
# 1. THE ANCHOR IS NOW MEASURED. v1.0.0 netted a measured inroad
#    (accords_normalization) against an UNMEASURED anchor -- "Palestinian-file
#    preconditions" was a phrase with no actor behind it, and counter_actor
#    pointed at iran_saudi instead. An axis that measures one side and asserts
#    the other can only ever drift one way. counter_actor is now
#    palestinian_file: Riyadh on Gaza, the West Bank and Lebanon.
#
# 2. THE IRAN-DETENTE HEDGE IS RETIRED AS AN ANCHOR. It was a holdout anchor
#    when Beijing-2023 was the live frame. There is now a war with Iran and
#    Houthi missiles reaching Riyadh; detente is not holding Riyadh back from
#    anything. detente_rupture stays as an INROAD tripwire (losing the hedge
#    strengthens the US-Israel security logic) but no longer anchors holdout.
#
# 3. THE ONE PATH THAT FORCES IT. israel_defense_transfer joins the inroad
#    tripwires. This is the UAE's documented road -- capability arriving under
#    fire normalizes faster than any summit.
DRIFT_PROFILES = {
    'saudi_arabia': {
        'flag':            '\U0001F1F8\U0001F1E6',
        'axis_label':      'Accords axis',          # short form, for short_text
        'inroad_power':    'the normalization track (US-brokered Israel package; Israeli defence capability under fire)',
        'incumbent_power': 'the holdout anchors Riyadh actually names (Gaza, the West Bank, Lebanon)',
        'inroad_actor':    'accords_normalization',
        # v1.1.0: was 'iran_saudi'. The anchor is the Palestinian file, and it
        # is now an actor rather than a phrase.
        'counter_actor':   'palestinian_file',
        'inroad_tripwires':  ('accords_signature', 'detente_rupture',
                              'israel_defense_transfer'),
        'counter_tripwires': (),
        'dependency_channel': ('the US security-guarantee package under negotiation (defense pact + '
                               'civil-nuclear track), and -- newly live since Oct 2026 -- the question '
                               'of whether Riyadh needs Israeli air-defence capability badly enough to '
                               'pay for it in signature'),
        'commodity_keys':     ('oil',),
        'crosstheater_amp':   'israel_fingerprint',
        'structural_dependency_baseline': False,   # the pact is NOT signed -- no drift floor
        'precedents': ("the UAE/Bahrain 2020 Accords sequence (holdout-to-signature in one diplomatic "
                       "season once the package priced); the 2023 pre-Oct-7 Saudi track that reached "
                       "'closer than ever' before re-anchoring; and the UAE's own wartime path, where "
                       "Israeli air-defence cooperation deepened under inbound fire rather than at a "
                       "summit table"),
        'leading_indicators': [
            'Gaza / West Bank / Lebanon language from Riyadh -- hardening re-anchors holdout, '
            'softening or SILENCE is the signature-adjacent tell',
            'Israeli defence capability toward Riyadh under fire (the UAE path; the one lever '
            'judged capable of forcing the hand)',
            'US-brokered package milestones (defense pact text, civil-nuclear terms)',
            'Israeli-overflight and business-access gestures (signature-adjacent tells)',
            'Accords-anniversary and summit signaling windows',
        ],
    },
}

_DRIFT_LEVEL_RANK = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}



print("[Saudi Arabia Signal Interpreter] Module loaded -- v%s" % MODULE_VERSION)
