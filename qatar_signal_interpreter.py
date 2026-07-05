"""
qatar_signal_interpreter.py -- Asifah Analytics ME Backend -- v1.0.0 Jul 2026
Analyst layer for rhetoric_tracker_qatar (mediation-class node).
5-function contract as canon. DRIFT AXIS: the OFF-RAMP AXIS -- channels-open <->
channels-closed. Bands: Channels-Open -> Strained -> Narrowing -> Channels-Closed.
Nets closure pressure (mediation collapse, office expulsion, blockade revival)
against channel anchors (mediation tempo, breakthroughs). Baseline sits at OPEN --
unusual among drift axes -- because Doha's default state is active channels.
Estimative voice. Convergence, not prediction. Tempo, not threat.
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
    'mediation_activity':  'Mediation Activity',
    'gcc_cohesion':        'GCC Cohesion',
    'gas_infrastructure':  'Gas Infrastructure',
    'base_posture':        'Base Posture',
}

VECTOR_MEMBERS = {
    'mediation_activity':  ('qatar_mofa_mediation', 'hamas_gaza_file', 'emir_leadership'),
    'gcc_cohesion':        ('gcc_relations',),
    'gas_infrastructure':  ('qatarenergy_lng', 'iran_qatar'),
    'base_posture':        ('al_udeid_us', 'turkey_qatar'),
}

# Actor display names for prose (cleaner than the formal `name` field)
ACTOR_PROSE_NAMES = {
    'qatar_mofa_mediation': 'the MOFA mediation track',
    'hamas_gaza_file':      'the Gaza/Hamas file',
    'emir_leadership':      'the Emiri leadership line',
    'qatarenergy_lng':      'QatarEnergy / North Field',
    'iran_qatar':           'the Iran condominium track',
    'al_udeid_us':          'the Al Udeid / US track',
    'turkey_qatar':         'the Turkish-garrison track',
    'gcc_relations':        'the GCC cohesion watch',
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
                       + ' across ' + esc_txt + '. Qatar supply-risk premium is '
                       'partly a political risk premium -- this composite and the '
                       'runoff count are stacking on the same window.'),
        'source_link': '/qatar-stability.html#commodities',
    }


def build_top_signals(actor_summaries, tripwires_global, commodity_pressure, crosstheater_amplifiers):
    """
    Build the canonical top_signals[] array for the Qatar rhetoric tracker.

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
    P = {
        'mediation_breakthrough': (
            "Doha-brokered breakthrough at tripwire confidence -- a DE-ESCALATORY event. Brokered "
            "agreements from active Qatari channels have historically preceded broader off-ramps; the "
            "Iran wheel consumes this as containment confirmation. Watch implementation vocabulary in "
            "the following week -- breakthroughs that hold produce follow-on rounds."),
        'mediation_collapse': (
            "Mediation-collapse vocabulary at tripwire confidence -- THE mediation-class pressure event. "
            "The exit ramp closing: escalation elsewhere without an active Doha channel is the no-exit "
            "pattern that has historically preceded uncontained cycles. The off-ramp axis swings hard on "
            "this tripwire."),
        'blockade_language_revival': (
            "2017-precedent vocabulary at tripwire confidence. Last cycle, this language preceded a "
            "four-year closure of Qatar's only land border, food-supply rerouting through Iran and "
            "Turkey, and an existential basing question. AlUla (2021) is a truce with a precedent -- "
            "revival vocabulary is never noise."),
        'north_field_incident': (
            "North Field / Ras Laffan incident signals at tripwire confidence -- a global LNG event by "
            "construction. Roughly a fifth of global LNG and the EU's post-Ukraine supply margin route "
            "through this infrastructure; TTF and JKM repricing is the by-construction consequence. "
            "Watch QatarEnergy operational statements and the shared-field median line."),
        'al_udeid_attack': (
            "Al Udeid attack signals at tripwire confidence -- an escalation class of its own. A strike "
            "on CENTCOM's forward HQ historically forces theater-wide US posture change and puts the "
            "response question on Washington's desk, not Doha's. Every regional file reprices "
            "simultaneously."),
        'hamas_office_expulsion': (
            "Hamas-office expulsion signals at tripwire confidence -- a mediation-posture rupture. The "
            "Gaza channel losing its Doha address removes the region's most-used negotiation venue; "
            "historically, venue loss has lengthened ceasefire gaps. The off-ramp axis reads this as "
            "closure pressure."),
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
        "Qatar's risk profile compounds across normally-independent dimensions."
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
    lvl = (actor or {}).get('level', 'low')
    de  = " De-escalatory vocabulary is present in the same window -- read the tempo against it." if deescalation else ""
    P = {
        'qatar_mofa_mediation':
            "MOFA mediation tempo at " + lvl + " -- the off-ramp sensor itself. For a mediation-class "
            "node this reads as ACTIVITY, not threat: shuttle visits, hosted rounds, and exchange "
            "vocabulary at this tempo have historically preceded regional de-escalation windows. "
            "Escalation elsewhere WITH this channel active has historically stayed contained.",
        'hamas_gaza_file':
            "Gaza-file tempo at " + lvl + ". The highest-profile portfolio in the mediation book -- "
            "round/hostage/ceasefire vocabulary here moves the regional off-ramp read directly. Office-"
            "status language is the rupture watch.",
        'emir_leadership':
            "Emiri leadership tempo at " + lvl + ". Summit appearances and sovereign-wealth vocabulary "
            "track Doha's strategic confidence; QIA deployment language transmits into global asset "
            "positioning within quarters.",
        'qatarenergy_lng':
            "QatarEnergy / North Field signal volume at " + lvl + ". NFE-milestone, contract, and cargo "
            "vocabulary at this tempo is the platform's most market-coupled Qatari read -- TTF and JKM "
            "absorb this vector within days when it concerns supply. Every cargo transits Hormuz.",
        'iran_qatar':
            "Iran condominium track at " + lvl + ". The shared North Field / South Pars geology forces "
            "structural pragmatism -- friction vocabulary on this spoke would be a structural rupture, "
            "not a Tuesday. Median-line and flight/trade vocabulary are the health gauges.",
        'al_udeid_us':
            "Al Udeid / US track at " + lvl + ". Base-posture and CENTCOM vocabulary at this tempo reads "
            "as the American anchor's health; threat language against the base is an escalation class of "
            "its own and the L5 gate's primary trigger.",
        'turkey_qatar':
            "Turkish-garrison track at " + lvl + ". The Tariq bin Ziyad base is the blockade-era "
            "guarantee made permanent -- exercise and reinforcement vocabulary reads as the alliance-"
            "insurance premium being paid on schedule.",
        'gcc_relations':
            "GCC cohesion watch at " + lvl + ". Intra-Gulf vocabulary reads against the 2017-2021 "
            "blockade precedent; rift language is never noise here. Summit outcomes, border/airspace "
            "signals, and food-corridor reporting are the confirmation gauges.",
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
        f"The commodity tracker is reporting {alert}-level pressure on Qatar's {commodity_id} "
        f"sector (Qatar is a {role}{rank_str}). {sig_count} cross-tracker signals flagged. "
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
            'The Pakistan tracker\'s crosstheater fingerprint is live and elevated. For Qatar '
            'this amplifies the Af-Pak kinetic vector: Pakistani domestic pressure has historically '
            'transmitted into harder Qatar policy (strikes, closures, deportation waves).'),
        'iran_fingerprint': (
            '\U0001f1ee\U0001f1f7 Iran wheel active -- friction-side amplification',
            'The Iran tracker\'s crosstheater fingerprint is live. Elevated Iranian theater pressure '
            'has historically hardened Tehran\'s Qatar file (water ultimatums, deportation '
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
        'category': 'crosstheater', 'theatre': 'qatar',
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
    _med = (asum.get('qatar_mofa_mediation') or {}).get('level', 'low')
    if _med in ('high', 'surge'):
        parts.append("Mediation channels at " + _med + " tempo -- for a mediation-class node this is "
                     "ACTIVITY, not threat; active Doha channels have historically preceded off-ramps. "
                     "Collapse, not tempo, is the pressure event.")
    else:
        parts.append("Mediation-class node: mediation activity reads as tempo, not threat -- collapse is "
                     "the pressure event. Condominium gas geology anchors Iran pragmatism. Convergence "
                     "read, not prediction.")
    return " ".join(parts)


def score_alignment_drift(actor_summaries, tripwires_global,
                          commodity_pressure, crosstheater_amplifiers,
                          country='qatar', profile=None):
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
        band = 'Channels-Open'
    elif inroad >= 2 and counter >= 2:
        band = 'Strained'
    elif inroad >= 5 and counter <= 1 and dep_active:
        band = 'Channels-Closed'
    elif (inroad - counter) >= 2:
        band = 'Narrowing'
    elif counter >= 2:
        band = 'Strained'
    else:
        band = 'Channels-Open'

    # structural-dependency floor: an entrenched, operational inroad means the
    # alignment has already structurally landed -- at minimum 'Drifting'.
    if prof.get('structural_dependency_baseline') and band == 'Channels-Open':
        band = 'Narrowing'

    ip = prof['inroad_power']; cp_ = prof['incumbent_power']; cc = 'Qatar'
    if band == 'Channels-Open':
        so_what = ("Closure-pressure signals read as routine regional friction rather than a converging "
                   "channel-rupture pattern; Doha's mediation channels are open and the anchors -- Al "
                   "Udeid trust plus condominium-gas pragmatism -- are uncontested this cycle.")
    elif band == 'Strained':
        so_what = ("Closure pressure and channel anchors are both active -- a strained-but-functioning "
                   "pattern consistent with " + prof['precedents'] + ". Channels are being tested, not lost.")
    elif band == 'Narrowing':
        so_what = ("Closure-pressure signals are outpacing the channel anchors; the pattern is consistent "
                   "with the region's off-ramp narrowing -- escalation elsewhere WITH Doha narrowing is "
                   "the combination that has historically preceded uncontained cycles.")
    else:  # Channels-Closed
        so_what = ("Sustained closure pressure with channel anchors failing is consistent with the "
                   "no-exit pattern: the region losing its most-used negotiation venue. Every open file "
                   "reprices simultaneously when the table disappears.")
    disclaimer = ("This is a CONVERGENCE indicator on the channels-open-to-closed axis, NOT a "
                  "prediction of mediation failure. It measures whether closure pressure is outpacing "
                  "channel anchors; Doha retains full agency over its mediation posture.")

    meta = DRIFT_BAND_META[band]
    return {
        'id':                'offramp_axis_' + (country or '').lower(),
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
        'mediation_activity': ("Mediation-activity at {lvl}. What it means: TEMPO, not threat -- active Doha "
            "channels have historically preceded regional off-ramps; escalation elsewhere WITH channels active "
            "has historically stayed contained, while the same escalation with channels quiet is the no-exit "
            "pattern. Who feels it: every open ME negotiation simultaneously. Confirmation gauges: shuttle-visit "
            "cadence, joint statements, the mediation_active fingerprint feeding the Iran wheel.", 0.95),
        'gcc_cohesion': ("GCC-cohesion at {lvl}. What it means: rift vocabulary at this tempo reads against "
            "the 2017-2021 blockade precedent -- last cycle it closed the only land border for four years, "
            "rerouted food supply through Iran and Turkey, and put the basing question in play. Who feels it: "
            "supply corridors, summit politics, US basing calculus. Confirmation gauges: border/airspace "
            "reporting, summit language, Hamad Port signals.", 0.9),
        'gas_infrastructure': ("Gas-infrastructure at {lvl}. What it means: Qatar ships roughly a fifth of "
            "global LNG and every cargo transits Hormuz -- signal tempo transmits to TTF and JKM within days, "
            "EU storage math within weeks, and power costs for import-dependent industry (Japan, Korea, "
            "Taiwan -- semiconductor fabs included) within a quarter. Who feels it first: EU utilities, Asian "
            "spot buyers, fertilizer producers. Confirmation gauges: the TTF tile is the live demand-side "
            "tell; Ras Laffan operations reporting.", 0.85),
        'base_posture': ("Base-posture at {lvl}. What it means: threat tempo against Al Udeid -- CENTCOM's "
            "forward HQ -- is an escalation class of its own; historically it forces theater-wide force-"
            "protection changes and puts every US regional operation on a different footing. Who feels it: US "
            "operations, Gulf basing politics, embassy advisories. Confirmation gauges: NOTAM clusters, "
            "CENTCOM posture statements.", 0.8),
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
    if alignment_drift and alignment_drift.get('band') not in (None, 'Channels-Open'):
        bullets.append({'weight': 0.92, 'bullet':
            "Off-ramp axis reads " + alignment_drift['band'] + ": " +
            (alignment_drift.get('so_what_factor') or '')})

    if not bullets:
        bullets.append({'weight': 0.3, 'bullet':
            "All four vectors at baseline this scan. For the mediation node, baseline quiet cuts both "
            "ways: no collapse signals, but channel tempo is the off-ramp sensor -- escalation elsewhere "
            "WITH Doha quiet would be the pattern that removes the exit. Tempo, not threat."})
    bullets.sort(key=lambda b: -b['weight'])
    return bullets[:6]

def interpret_qatar_signals(scan_data):
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
                                  country='qatar')
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


print("[Qatar Signal Interpreter] Module loaded — v1.0.0")
DRIFT_BAND_META = {
    'Channels-Open':   {'level': 1, 'color': '#22c55e', 'priority': 8},
    'Strained':        {'level': 3, 'color': '#f59e0b', 'priority': 12},
    'Narrowing':       {'level': 4, 'color': '#f97316', 'priority': 13},
    'Channels-Closed': {'level': 5, 'color': '#dc2626', 'priority': 14},
}

DRIFT_PROFILES = {
    'qatar': {
        'flag':            '\U0001F1F6\U0001F1E6',
        'inroad_power':    'channel-closure pressure (collapse signals, expulsion pressure, blockade-revival vocabulary)',
        'incumbent_power': 'the channel anchors (active mediation tempo, hosted rounds, both-sides trust)',
        'inroad_actor':    'gcc_relations',
        'counter_actor':   'qatar_mofa_mediation',
        'inroad_tripwires':  ('mediation_collapse', 'hamas_office_expulsion', 'blockade_language_revival'),
        'counter_tripwires': ('mediation_breakthrough',),
        'dependency_channel': 'the Al Udeid hosting relationship and the shared North Field geology that anchor trust with both Washington and Tehran',
        'commodity_keys':     ('gas',),
        'crosstheater_amp':   'iran_fingerprint',
        'structural_dependency_baseline': False,
        'precedents': ("the 2017-2021 blockade (channels survived even total GCC rupture) and the "
                       "2023-2025 Gaza rounds (venue persistence through repeated collapse-and-restart cycles)"),
        'leading_indicators': [
            'Shuttle-visit and hosted-round cadence (the tempo gauge itself)',
            'Hamas political-office status vocabulary (venue-rupture watch)',
            'GCC summit language and border/airspace signals (blockade-precedent lens)',
            'Al Udeid posture statements (the US-side trust anchor)',
            'Iran-file median-line and flight/trade signals (the Tehran-side trust anchor)',
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



def interpret_qatar_signals(scan_data):
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
                                  country='qatar')
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



