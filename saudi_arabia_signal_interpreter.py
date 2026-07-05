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

import re
from datetime import datetime, timezone

# ============================================
# CONFIGURATION
# ============================================
LEVEL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']
ESCALATORY_LEVELS = {'elevated', 'high', 'surge'}

# Vector display names for prose
VECTOR_NAMES = {
    'kinetic_inbound':         'Kinetic Inbound',
    'energy_infrastructure':   'Energy Infrastructure',
    'normalization_watch':     'Normalization Watch',
    'domestic_transformation': 'Domestic Transformation',
}

VECTOR_MEMBERS = {
    'kinetic_inbound':         ('houthi_yemen', 'saudi_mod_airdefense', 'iran_saudi'),
    'energy_infrastructure':   ('aramco_energy', 'opec_policy'),
    'normalization_watch':     ('accords_normalization', 'us_saudi', 'gcc_saudi'),
    'domestic_transformation': ('royal_court_mbs', 'vision2030_domestic'),
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
                       'partly a political risk premium -- this composite and the '
                       'runoff count are stacking on the same window.'),
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
        top_art = _top_article_for_actor(actor_data) if actor_data else None
        sources = []
        if top_art:
            sources.append({
                'title':  top_art.get('title', ''),
                'url':    top_art.get('url', ''),
                'source': top_art.get('source', ''),
            })

        short, long_text = _tripwire_prose(tw_id, actor_id)
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
        if not amp_data.get('active'):
            continue
        sig = _crosstheater_signal(amp_label, amp_data)
        if sig:
            signals.append(sig)

    # Sort: surge → high → elevated → normal → low; within same level, signals with sources first
    signals.sort(
        key=lambda s: (-_level_rank(s['level']), -len(s.get('sources', [])))
    )
    # Composite commodity story rides high when escalated (mirrors stability page)
    _cs = _commodity_story_signal(commodity_pressure)
    if _cs:
        signals.insert(0, _cs)
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
            "external file (Iran detente, Accords, US pact) gets re-anchored at once. Watch allegiance-"
            "council reporting and decree tempo."),
        'detente_rupture': (
            "Detente-rupture vocabulary at tripwire confidence. The Beijing-2023 normalization track is "
            "the friction tier's brake -- rupture removes it. Historically, friction spikes WITHOUT the "
            "detente channel have escalated further than identical spikes with the channel intact. This "
            "also accelerates the Accords drift axis: losing the Iran hedge strengthens the US-Israel "
            "security logic."),
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
    long_text = ' '.join(long_parts) if False else '\n'.join(long_parts)
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
        short = f"{icon} {name} — {level} but with de-escalatory rhetoric (dialogue / consulta previa)"
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
        f"This is a coupling event — what the rhetoric tracker observes in illicit_economy / "
        f"wheat/corridor channels has a direct supply-side implication for global {commodity_id} "
        f"markets. Watch for sector-rhetoric and price-impact alignment."
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
        'actor':      'drug_economy',
        'sources':    sources,
    }


def _crosstheater_signal(amp_label, amp_data):
    """Signal for an active sibling-wheel fingerprint (absence-honest: only called when present)."""
    prose = {
        'pakistan_fingerprint': (
            '\U0001f1f5\U0001f1f0 Pakistan wheel active -- kinetic-side amplification',
            'The Pakistan tracker\'s crosstheater fingerprint is live and elevated. For Saudi Arabia '
            'this amplifies the Af-Pak kinetic vector: Pakistani domestic pressure has historically '
            'transmitted into harder Saudi Arabia policy (strikes, closures, deportation waves).'),
        'iran_fingerprint': (
            '\U0001f1ee\U0001f1f7 Iran wheel active -- friction-side amplification',
            'The Iran tracker\'s crosstheater fingerprint is live. Elevated Iranian theater pressure '
            'has historically hardened Tehran\'s Saudi Arabia file (water ultimatums, deportation '
            'acceleration, border posture) -- friction-spoke amplification on the contested node.'),
        'china_fingerprint': (
            '\U0001f1e8\U0001f1f3 China wheel active -- extraction-track amplification',
            'The China tracker\'s crosstheater fingerprint is live. Elevated Chinese theater activity '
            'is consistent with accelerated extraction-track positioning in Kabul (Mes Aynak, Amu '
            'Darya) -- the dependency channel of the normalization-drift read.'),
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
    """Portable great-power alignment-drift convergence read ("BRI writ large").
    Nets challenger (China/BRI) inroad pressure against incumbent (US) counter-
    pressure: US-anchored -> Contested -> Drifting -> Realigning. Registry-shaped
    output (id: bri_inroad_<country>). CONVERGENCE, not prediction."""
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

    amp_active = bool((crosstheater_amplifiers or {}).get(prof.get('crosstheater_amp', '')))

    inroad  = inroad_lvl + len(inroad_tw) + (1 if dep_active else 0) + (1 if amp_active else 0)
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
                   "signature pattern; the holdout anchors -- Palestinian-file preconditions and the Iran-"
                   "detente hedge -- are uncontested this cycle.")
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
    """Canonical-schema top_signal for the alignment-drift read -> regional BLUF / GPI.
    Returns None for US-anchored (calm baseline)."""
    if not drift or drift.get('band') in (None, 'US-anchored'):
        return None
    return {
        'priority':   drift['priority'],
        'category':   'alignment_drift',
        'theatre':    drift['country'],
        'level':      drift['level'],
        'icon':       drift['icon'],
        'color':      drift['color'],
        'short_text': (drift['flag'] + ' ' + drift['country'].upper() + ': ' +
                       drift['inroad_power'] + ' alignment drift -- ' + drift['band']),
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


print("[Saudi Arabia Signal Interpreter] Module loaded — v1.0.0")
DRIFT_BAND_META = {
    'Holdout':         {'level': 1, 'color': '#38bdf8', 'priority': 8},
    'Warming':         {'level': 3, 'color': '#f59e0b', 'priority': 12},
    'Converging':      {'level': 4, 'color': '#f97316', 'priority': 13},
    'Signature-Track': {'level': 5, 'color': '#dc2626', 'priority': 14},
}

DRIFT_PROFILES = {
    'saudi_arabia': {
        'flag':            '\U0001F1F8\U0001F1E6',
        'inroad_power':    'the normalization track (US-brokered Israel package)',
        'incumbent_power': 'the holdout anchors (Palestinian-file preconditions + the Iran-detente hedge)',
        'inroad_actor':    'accords_normalization',
        'counter_actor':   'iran_saudi',
        'inroad_tripwires':  ('accords_signature', 'detente_rupture'),
        'counter_tripwires': (),
        'dependency_channel': 'the US security-guarantee package under negotiation (defense pact + civil-nuclear track)',
        'commodity_keys':     ('oil',),
        'crosstheater_amp':   'israel_fingerprint',
        'structural_dependency_baseline': False,   # the pact is NOT signed -- no drift floor
        'precedents': ("the UAE/Bahrain 2020 Accords sequence (holdout-to-signature in one diplomatic "
                       "season once the package priced), and the 2023 pre-Oct-7 Saudi track that reached "
                       "'closer than ever' before re-anchoring"),
        'leading_indicators': [
            'US-brokered package milestones (defense pact text, civil-nuclear terms)',
            'Palestinian-state precondition language -- hardening or softening',
            'Iran-detente channel health (embassy/hajj/trade signals; rupture = accelerant)',
            'Israeli-overflight and business-access gestures (signature-adjacent tells)',
            'Accords-anniversary and summit signaling windows',
        ],
    },
}

_DRIFT_LEVEL_RANK = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}



def build_alignment_drift_top_signal(drift):
    """Canonical-schema top_signal for the alignment-drift read -> regional BLUF / GPI.
    Returns None for US-anchored (calm baseline)."""
    if not drift or drift.get('band') in (None, 'US-anchored'):
        return None
    return {
        'priority':   drift['priority'],
        'category':   'alignment_drift',
        'theatre':    drift['country'],
        'level':      drift['level'],
        'icon':       drift['icon'],
        'color':      drift['color'],
        'short_text': (drift['flag'] + ' ' + drift['country'].upper() + ': ' +
                       drift['inroad_power'] + ' alignment drift -- ' + drift['band']),
        'long_text':  ((drift['so_what_factor'] + ' ' + drift['disclaimer'])[:480]),
    }



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



