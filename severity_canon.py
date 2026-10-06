"""
severity_canon.py -- Asifah Analytics
================================================================================
ONE WRITER FOR EVERY LADDER THE PLATFORM USES.

THE PROBLEM THIS SOLVES
-----------------------
Four separate tables translate status words into the platform's numeric level,
each written independently, and they disagree:

    word        commodity_tracker    global_pressure_index    me_regional_bluf
                _COMMODITY_BLUF_LEVEL  _LEVEL_LABEL_MAP        _BAND_TO_LEVEL
    elevated    3                      3                       2
    high        4                      4                       3
    normal      0                      1                       0
    critical    --                     5                       4

So the same word becomes a different number depending on which function happens
to see it, and nothing anywhere declares which answer is right.

THE INSIGHT: THE UNIT IS NOT THE WORD, IT IS (LADDER, RUNG)
-----------------------------------------------------------
"elevated" is ambiguous and always was. A commodity at ELEVATED and a rhetoric
vector at ELEVATED are readings on DIFFERENT instruments that happen to share an
English word, and they genuinely should not translate to the same platform level.
The bug was never that the numbers differ -- it is that nothing said which ladder
an incoming word belonged to, so each function guessed, and they guessed
differently.

This module makes the ladder explicit. Every lookup names its instrument:

    to_platform('commodity_alert', 'elevated')  -> 3
    to_platform('rhetoric_band',   'elevated')  -> 2

Both are correct. They were always meant to be different.

THE RULE THAT KEEPS THIS HONEST -- AN UNKNOWN RUNG IS NOT A ZERO
----------------------------------------------------------------
Every lookup returns None for a rung this module does not recognise. NEVER 0.

This is the single most important line in the file. `_LEVEL_LABEL_MAP` carries a
comment admitting that 'high' was missing from it until June 18 2026 and was
therefore coerced to 0 -- the platform's loudest commodity reading rendering as
silence for weeks, because a dict miss defaulted to the quiet end. A missing key
must be loud, not quiet. Callers decide what to do with None; this module will
not decide for them by inventing a floor.

WHAT THIS MODULE IS NOT
-----------------------
It does not fetch, cache, or write anything. No Redis, no HTTP, no Flask, no
third-party imports. It is a lookup table with a conscience, which is what lets
it deploy BYTE-IDENTICAL to all five backends the way spoke_wheel_reader.py does.

MIGRATION POSTURE
-----------------
Shipping this file changes NOTHING on its own. Nothing imports it yet. The
existing four tables keep running untouched. Each module migrates separately,
and `parity_report()` says in advance exactly which inputs would change answer
if it did -- so no arithmetic flips without someone having read the list first.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

__version__ = '1.1.0'
CANON_AS_OF = '2026-10-06'


# ════════════════════════════════════════════════════════════════════
# THE PLATFORM LADDER -- the one every other ladder translates INTO
# ════════════════════════════════════════════════════════════════════
# 0-6. This is the ladder the GPI publishes, the regional BLUFs carry, and the
# "How to read this" box on the pages explains. Its rungs mean different things
# on different axes, which is why each axis gets its own wording below.

# CORRECTED Oct 6 2026, same day it was written. The first version of this
# table invented its own words -- QUIET / SIGNAL / BUILDING / HARDENING / ACUTE /
# RUPTURE -- while asifah-standard-shell.js has shipped Monitoring / Rhetoric /
# Warning / Confrontation / Coercion / Active Conflict to every page since Oct 3.
#
# That made this module a FIFTH competing ladder, inside the file written to stop
# exactly that. The shell's words win and always should have: they are on screen,
# the reader has seen them, and they were chosen deliberately -- the shell carries
# a design note explaining why L0 is "Monitoring" (the scan is running and found
# nothing) rather than "Baseline" (we assessed it as normal). That distinction is
# the difference between a page reading dead and reading alive, and it is not a
# distinction to casually overwrite from a backend module nobody looks at.
#
# THE RULE THIS ESTABLISHES: the canon RECORDS the platform's vocabulary. It does
# not get to invent any. Where a word already exists on screen, the screen wins.
#
# L6 is carried here and is NOT in the shell's table. The axis strings go to L6
# ('red line breached'), and _safe_level can return 6, so a page can render an L6
# chip the guide cannot explain. Flagged in PENDING_RULINGS rather than silently
# papered over.
PLATFORM_LEVELS = {
    0: {'key': 'monitoring',      'display': 'Monitoring',      'color': '#6b7280',
        'gloss': 'Nothing above normal. The scan is running.'},
    1: {'key': 'rhetoric',        'display': 'Rhetoric',        'color': '#3b82f6',
        'gloss': 'Talk, with no named target.'},
    2: {'key': 'warning',         'display': 'Warning',         'color': '#f59e0b',
        'gloss': 'Talk directed at a named target.'},
    3: {'key': 'confrontation',   'display': 'Confrontation',   'color': '#f97316',
        'gloss': 'Direct and mutual \u2014 both sides engaged.'},
    4: {'key': 'coercion',        'display': 'Coercion',        'color': '#ef4444',
        'gloss': 'Pressure applied to extract a concession.'},
    5: {'key': 'active_conflict', 'display': 'Active Conflict', 'color': '#dc2626',
        'gloss': 'Open hostilities underway.'},
    6: {'key': 'red_line',        'display': 'Red Line Breached', 'color': '#991b1b',
        'gloss': 'A stated red line has been crossed.'},
}

# The authority for the words above. A drift test asserts the two still agree.
PLATFORM_LEVELS_SOURCE = 'asifah-standard-shell.js ASIFAH_LADDER (Oct 3 2026)'

# What a level MEANS depends on the axis it sits on. These are the strings the
# page guide renders, and they are the authority for that guide -- the box stops
# being hand-maintained prose that can drift from the arithmetic.
AXIS_MEANINGS = {
    'kinetic': {
        'label': 'Kinetic',
        'rungs': {0: 'quiet', 1: 'rhetorical signalling', 2: 'pressure building',
                  3: 'standoff hardening', 4: 'armed incident',
                  5: 'active war footing', 6: 'red line breached'},
    },
    'humanitarian': {
        'label': 'Humanitarian',
        'rungs': {3: 'humanitarian conditions deteriorating',
                  4: 'acute humanitarian emergency',
                  5: 'mass-casualty humanitarian disaster',
                  6: 'catastrophic humanitarian collapse'},
    },
    'economic': {
        'label': 'Economic',
        'rungs': {3: 'supply pressure hardening', 4: 'acute supply disruption',
                  5: 'economic rupture', 6: 'systemic economic breakdown'},
    },
    'diplomatic': {
        'label': 'Diplomatic',
        'rungs': {3: 'diplomatic standoff', 4: 'talks collapsed',
                  5: 'diplomatic rupture', 6: 'relations severed'},
    },
}


# ════════════════════════════════════════════════════════════════════
# THE INSTRUMENT LADDERS
# ════════════════════════════════════════════════════════════════════
# Each entry declares:
#   label        what a reader should call this instrument
#   measures     what it actually measures, in plain words. Goes in the UI guide.
#   rungs        rung -> {rank, display, to_platform, means}
#                rank       ordering WITHIN this ladder (for sorting/thresholds)
#                to_platform the platform level this rung translates to, or None
#                           when the rung is an ABSENCE rather than a reading
#   absence      rungs that mean "not read", which must never be ranked or
#                translated as if they were a low reading
#   source       which file this was reconstructed from, so provenance survives

LADDERS = {

    # ── Commodity news-signal pressure ────────────────────────────────
    # Matches ALERT_RANK (commodity_signal_interpreter) for rank and
    # _COMMODITY_BLUF_LEVEL (commodity_tracker) for to_platform. Those two
    # already agreed; they were simply written down twice.
    'commodity_alert': {
        'label': 'Commodity pressure',
        'measures': ('Weighted volume and severity of matched reporting this '
                     'scan. NOT spot price, and not a forecast of price.'),
        'source': 'ALERT_RANK + _COMMODITY_BLUF_LEVEL',
        'rungs': {
            'normal':   {'rank': 0, 'display': 'NORMAL',   'to_platform': 0,
                         'means': 'routine coverage, nothing above baseline'},
            'monitor':  {'rank': 1, 'display': 'MONITORED','to_platform': 2,
                         'means': 'above routine, below the elevated threshold'},
            'elevated': {'rank': 2, 'display': 'ELEVATED', 'to_platform': 3,
                         'means': 'sustained above-baseline reporting'},
            'high':     {'rank': 3, 'display': 'HIGH',     'to_platform': 4,
                         'means': 'heavy and severe reporting concentration'},
            'surge':    {'rank': 4, 'display': 'SURGE',    'to_platform': 5,
                         'means': 'the loudest band this instrument has'},
        },
        'absence': ('unknown', 'unread'),
    },

    # ── Corridor / chokepoint physical state ──────────────────────────
    # From corridor_dependence.CORRIDOR_SEVERITY. 'unknown' is deliberately
    # absent from that table and stays absent here: a corridor with no record
    # is NOT open.
    'corridor_state': {
        'label': 'Corridor state',
        'measures': ('Whether a physical route is passable. An EDGE reading, '
                     'not a country reading.'),
        'source': 'corridor_dependence.CORRIDOR_SEVERITY',
        'rungs': {
            'open':     {'rank': 0, 'display': 'OPEN',     'to_platform': 0,
                         'means': 'passable, measured and quiet'},
            'strained': {'rank': 1, 'display': 'STRAINED', 'to_platform': 2,
                         'means': 'passable at cost or delay'},
            'impaired': {'rank': 2, 'display': 'IMPAIRED', 'to_platform': 4,
                         'means': 'partially closed, substitution forced'},
            'blocked':  {'rank': 3, 'display': 'BLOCKED',  'to_platform': 5,
                         'means': 'not passable'},
        },
        'absence': ('unknown',),
    },

    # ── Chokepoint status ─────────────────────────────────────────────
    # A THIRD corridor vocabulary, distinct from corridor_state. ALERT_RANK
    # carries 'contested': 3 and 'disrupted': 4 as "chokepoint vocab", and the
    # military tracker stamps chokepoints with alert_level 'contested' /
    # 'disrupted'. Neither word appears in _LEVEL_LABEL_MAP, so a chokepoint
    # word reaching _safe_level hits the default.
    #
    # NOT VERIFIED AS LIVE: the instances found in military_signal_interpreter
    # were inside its __main__ self-test block. Whether military_tracker.py
    # emits these into a signal `level` that reaches the GPI has not been
    # checked -- military_tracker.py was not read. Declared here because the
    # ladder is correct either way; the question is only how much it matters.
    'chokepoint_status': {
        'label': 'Chokepoint status',
        'measures': ('Whether a named maritime chokepoint is transiting '
                     'normally. A narrower instrument than corridor_state: it '
                     'reads one strait, not a whole supply route.'),
        'source': 'ALERT_RANK chokepoint vocab + military tracker alert_level',
        'rungs': {
            'open':      {'rank': 0, 'display': 'OPEN',      'to_platform': 0,
                          'means': 'transiting normally'},
            'contested': {'rank': 3, 'display': 'CONTESTED', 'to_platform': 4,
                          'means': 'transit under active threat or interference'},
            'disrupted': {'rank': 4, 'display': 'DISRUPTED', 'to_platform': 5,
                          'means': 'transit materially interrupted'},
        },
        'absence': ('unknown',),
    },

    # ── Cascade chain tier ────────────────────────────────────────────
    # From cascade_detector. Its levels ARE platform levels already; recorded
    # here so the ladder is declared rather than implied.
    'cascade_tier': {
        'label': 'Cascade tier',
        'measures': ('How far a chokepoint -> intermediate -> downstream chain '
                     'has propagated. Reports that the setup is present, never '
                     'that an outcome will follow.'),
        'source': 'cascade_detector tier logic',
        'rungs': {
            'baseline':   {'rank': 0, 'display': 'BASELINE',   'to_platform': 0,
                           'means': 'no chain active'},
            'monitoring': {'rank': 1, 'display': 'MONITORING', 'to_platform': 1,
                           'means': 'partial signals on one chain'},
            'watch':      {'rank': 2, 'display': 'CASCADE WATCH', 'to_platform': 2,
                           'means': 'intermediate stress, or chokepoint plus one downstream'},
            'active':     {'rank': 4, 'display': 'CASCADE ACTIVE', 'to_platform': 4,
                           'means': 'chokepoint plus intermediate plus three downstream'},
            'compound':   {'rank': 5, 'display': 'COMPOUND CASCADE', 'to_platform': 5,
                           'means': 'two or more chains simultaneously active'},
        },
        'absence': (),
    },

    # ── GDACS disaster alert ──────────────────────────────────────────
    # From disaster_feeds.GDACS_ALERT_SEVERITY. Green is scored 0 and is NOT
    # emitted upstream -- recorded so that choice is visible rather than folklore.
    'gdacs_alert': {
        'label': 'Disaster alert (GDACS)',
        'measures': ('Modelled IMPACT -- population exposure and vulnerability -- '
                     'not raw physical magnitude.'),
        'source': 'disaster_feeds.GDACS_ALERT_SEVERITY',
        'rungs': {
            'green':  {'rank': 0, 'display': 'GREEN',  'to_platform': 0,
                       'means': 'routine event, negligible modelled impact'},
            'orange': {'rank': 2, 'display': 'ORANGE', 'to_platform': 4,
                       'means': 'significant modelled impact'},
            'red':    {'rank': 3, 'display': 'RED',    'to_platform': 5,
                       'means': 'severe modelled impact'},
        },
        'absence': (),
    },

    # ── Rhetoric band / posture ───────────────────────────────────────
    # From me_regional_bluf._BAND_TO_LEVEL. THIS is the ladder whose 'elevated'
    # is 2 rather than 3, and it is RIGHT to differ: a vector described as
    # "elevated" by a rhetoric tracker is a weaker claim than a commodity at
    # ELEVATED, which is a measured concentration. Same word, different
    # instrument, and naming the ladder is what finally lets both be correct.
    # ══════════════════════════════════════════════════════════
    # v1.1.0 (Oct 6 2026) -- GREECE VECTOR BAND
    #
    # THE CASE THAT PROVED THIS MODULE'S THESIS IN PRODUCTION.
    #
    # On 6 Oct 2026 the Europe BLUF reported "Greece -- active war footing (L5)".
    # Greece was not at war. rhetoric_tracker_greece carries its OWN six-rung
    # ladder, never routed through this file, and it collides with the platform
    # ladder in three places at once:
    #
    #   Greece L3 'Crisis'         the WORD 'crisis' resolves to platform 5 here
    #   Greece L4 'Confrontation'  the WORD 'confrontation' IS platform 3
    #   Greece L5 'Rupture'        the WORD 'rupture' resolves to platform 4 here
    #
    # The integer 5 crossed a backend boundary and the meaning did not. Greece's
    # L5 means "detente collapse, ambassadorial recall"; the platform's L5 means
    # open hostilities. Nothing translated, so the GPI printed a war.
    #
    # THE CAP, AND WHY IT IS NOT TIMIDITY
    # -----------------------------------
    # Greece's rung 5 reads "Maximal -- kinetic, detente collapse, ambassadorial
    # recall". Those are not one thing. A tracker whose top rung cannot
    # distinguish a kinetic exchange from a recalled ambassador has not earned
    # the right to assert platform 5 ACTIVE CONFLICT, because it has no sensor
    # that separates them. So rungs 4 AND 5 both land on platform 4, and this
    # ladder cannot emit a 5 until the rung is split.
    #
    # Deliberate information loss, declared out loud, native reading preserved
    # alongside. The alternative -- passing the integer through -- is what
    # printed "active war footing" for a diplomatic row.
    # ══════════════════════════════════════════════════════════
    'greece_vector_band': {
        'label': 'Greece vector band',
        'measures': ('The per-vector intensity rung rhetoric_tracker_greece assigns '
                     'each of its six vectors. A LOCAL ladder with local words; its '
                     'integers are NOT platform levels and must be translated.'),
        'source': 'rhetoric_tracker_greece.ESCALATION_LEVELS',
        'rungs': {
            'baseline':      {'rank': 0, 'display': 'BASELINE',      'to_platform': 0,
                              'means': 'routine diplomatic noise, no active friction'},
            'rhetoric':      {'rank': 1, 'display': 'RHETORIC',      'to_platform': 1,
                              'means': 'statements and framing, no concrete moves'},
            'pressure':      {'rank': 2, 'display': 'PRESSURE',      'to_platform': 2,
                              'means': 'concrete moves -- drills, NAVTEX, deportations'},
            'crisis':        {'rank': 3, 'display': 'CRISIS',        'to_platform': 3,
                              'means': ('significant escalation -- formal protest, incident. '
                                        'The word "crisis" means platform 5 on the '
                                        'rhetoric_band ladder: same word, different ladder, '
                                        'different answer, which is the whole point.')},
            'confrontation': {'rank': 4, 'display': 'CONFRONTATION', 'to_platform': 4,
                              'means': ('militarized incident, recall, casus belli '
                                        'activation. "Confrontation" is the platform word '
                                        'for 3, not 4.')},
            'rupture':       {'rank': 5, 'display': 'RUPTURE',       'to_platform': 4,
                              'means': ('detente collapse / ambassadorial recall -- CAPPED '
                                        'at platform 4. This rung conflates kinetic action '
                                        'with diplomatic rupture, so it cannot assert '
                                        'ACTIVE CONFLICT. See PENDING_RULINGS.')},
        },
    },

    'rhetoric_band': {
        'label': 'Rhetoric band',
        'measures': ('The posture word a tracker assigns a vector or actor. '
                     'A descriptive band, not a measured concentration.'),
        'source': 'me_regional_bluf._BAND_TO_LEVEL',
        'rungs': {
            'quiet':      {'rank': 0, 'display': 'QUIET',      'to_platform': 0, 'means': 'nothing moving'},
            'baseline':   {'rank': 0, 'display': 'BASELINE',   'to_platform': 0, 'means': 'routine'},
            'normal':     {'rank': 0, 'display': 'NORMAL',     'to_platform': 0, 'means': 'routine'},
            'stable':     {'rank': 0, 'display': 'STABLE',     'to_platform': 0, 'means': 'routine'},
            'holding':    {'rank': 0, 'display': 'HOLDING',    'to_platform': 0, 'means': 'unchanged this cycle'},
            'dormant':    {'rank': 0, 'display': 'DORMANT',    'to_platform': 0, 'means': 'inactive'},
            'watch':      {'rank': 1, 'display': 'WATCH',      'to_platform': 1, 'means': 'worth following'},
            'rhetorical': {'rank': 1, 'display': 'RHETORICAL', 'to_platform': 1, 'means': 'words only'},
            'friction':   {'rank': 1, 'display': 'FRICTION',   'to_platform': 1, 'means': 'low-grade abrasion'},
            'approaching':{'rank': 1, 'display': 'APPROACHING','to_platform': 1, 'means': 'nearing a threshold, not past it'},
            'tilting':    {'rank': 1, 'display': 'TILTING',    'to_platform': 1, 'means': 'leaning, not committed'},
            'drifting':   {'rank': 1, 'display': 'DRIFTING',   'to_platform': 1, 'means': 'moving without decision'},
            'monitoring': {'rank': 1, 'display': 'MONITORING', 'to_platform': 1, 'means': 'under observation, nothing yet to call'},
            'alignment':  {'rank': 0, 'display': 'ALIGNMENT',  'to_platform': 0, 'means': 'positions converged, no friction'},
            'low':        {'rank': 0, 'display': 'LOW',        'to_platform': 0, 'means': 'minimal'},
            'simmering':  {'rank': 2, 'display': 'SIMMERING',  'to_platform': 2, 'means': 'sustained low heat'},
            # Rachel's Oct 6 ruling on the _LEVEL_LABEL_MAP orphans: alert,
            # rising and tensions all sit with 'heightened' -- i.e. the rank-2
            # family. Worth recording that NOTHING in the backend emits
            # 'heightened' or 'tensions' as a level value, and 'rising' appears
            # exactly once (its own definition in _LEVEL_LABEL_MAP). They are
            # defensive vocabulary for words no module produces. Carried anyway:
            # a word the canon knows and nobody sends costs nothing, while a word
            # a module sends and the canon does not know becomes a zero.
            'heightened': {'rank': 2, 'display': 'HEIGHTENED', 'to_platform': 2, 'means': 'raised above the normal footing'},
            'alert':      {'rank': 2, 'display': 'ALERT',      'to_platform': 2, 'means': 'an explicit alert has been issued'},
            'rising':     {'rank': 2, 'display': 'RISING',     'to_platform': 2, 'means': 'moving upward, direction clear'},
            'tensions':   {'rank': 2, 'display': 'TENSIONS',   'to_platform': 2, 'means': 'friction named by the reporting'},
            'contested':  {'rank': 2, 'display': 'CONTESTED',  'to_platform': 2, 'means': 'actively disputed'},
            'elevated':   {'rank': 2, 'display': 'ELEVATED',   'to_platform': 2, 'means': 'above baseline posture'},
            'strained':   {'rank': 2, 'display': 'STRAINED',   'to_platform': 2, 'means': 'under load'},
            'warning':    {'rank': 2, 'display': 'WARNING',    'to_platform': 2, 'means': 'explicit warning language'},
            'active':     {'rank': 3, 'display': 'ACTIVE',     'to_platform': 3, 'means': 'engaged'},
            'high':       {'rank': 3, 'display': 'HIGH',       'to_platform': 3, 'means': 'hardened posture'},
            'fracturing': {'rank': 3, 'display': 'FRACTURING', 'to_platform': 3, 'means': 'cohesion failing'},
            'eroding':    {'rank': 3, 'display': 'ERODING',    'to_platform': 3, 'means': 'position degrading'},
            'acute':      {'rank': 4, 'display': 'ACUTE',      'to_platform': 4, 'means': 'sharp and current'},
            'severe':     {'rank': 4, 'display': 'SEVERE',     'to_platform': 4, 'means': 'serious'},
            'critical':   {'rank': 4, 'display': 'CRITICAL',   'to_platform': 4, 'means': 'at the edge'},
            'breached':   {'rank': 4, 'display': 'BREACHED',   'to_platform': 4, 'means': 'a stated line crossed'},
            'incident':   {'rank': 4, 'display': 'INCIDENT',   'to_platform': 4, 'means': 'a discrete armed or kinetic event'},
            'rupture':    {'rank': 4, 'display': 'RUPTURE',    'to_platform': 4, 'means': 'relationship broken'},
            'surge':      {'rank': 5, 'display': 'SURGE',      'to_platform': 5, 'means': 'peak'},
            'conflict':   {'rank': 5, 'display': 'CONFLICT',   'to_platform': 5, 'means': 'fighting'},
            # PROPOSED, not ruled on. 'crisis' reads as a rank-5 word and
            # 'incident' as rank-4 -- an armed incident is L4 on the kinetic
            # axis, which is where the platform ladder already puts it. Both are
            # flagged in PENDING_RULINGS so they are visibly provisional rather
            # than quietly settled.
            'crisis':     {'rank': 5, 'display': 'CRISIS',     'to_platform': 5, 'means': 'open crisis'},
            'war':        {'rank': 5, 'display': 'WAR',        'to_platform': 5, 'means': 'war footing'},
        },
        # DELIBERATE DIVERGENCE from the live _BAND_TO_LEVEL, which maps
        # 'unknown' -> 0. That is the bug this whole module exists to stop: a
        # vector nobody could read rendering as a vector that is quiet. Here
        # 'unknown' is an absence and returns None. Migrating this table will
        # therefore CHANGE behaviour for unread vectors, on purpose, and the
        # parity report flags it rather than slipping it past.
        'absence': ('unknown', 'unread', 'inactive', 'off', 'none'),
    },
}

# ════════════════════════════════════════════════════════════════════
# FAMILIES -- one headline word per rung, synonyms underneath
# ════════════════════════════════════════════════════════════════════
# Rachel's sidebar design, Oct 6: show the level once in full size, and the
# other words that mean the same level in small print beneath it.
#
#       HEIGHTENED
#       elevated · warning · alert · rising · tensions · contested · simmering
#
# Implemented as families rather than aliases ON PURPOSE. Collapsing those words
# into one entry would throw away their individual `means` text, and CONTESTED
# and SIMMERING are not synonyms -- they are different findings that land on the
# same rung. The family is a presentation grouping; the rungs stay distinct.

FAMILY_NAMES = {
    'commodity_alert': {
        0: ('NORMAL',     'routine coverage'),
        1: ('MONITORED',  'above routine, below the elevated threshold'),
        2: ('ELEVATED',   'sustained above-baseline reporting'),
        3: ('HIGH',       'heavy and severe reporting concentration'),
        4: ('SURGE',      'the loudest band this instrument has'),
    },
    'rhetoric_band': {
        0: ('QUIET',      'measured, nothing moving'),
        1: ('MONITORING', 'worth following, nothing to call yet'),
        2: ('HEIGHTENED', 'above baseline, direction not yet decided'),
        3: ('HARDENED',   'positions set, engagement under way'),
        4: ('ACUTE',      'sharp, current, a line at or past its edge'),
        # NOT 'RUPTURE': _BAND_TO_LEVEL puts the word 'rupture' at rank 4, so
        # naming the rank-5 family RUPTURE would print the same word as both a
        # headline and a member of the rung below it.
        5: ('CONFLICT',   'open conflict'),
    },
    'corridor_state': {
        0: ('OPEN',       'passable, measured and quiet'),
        1: ('STRAINED',   'passable at cost or delay'),
        2: ('IMPAIRED',   'partially closed, substitution forced'),
        3: ('BLOCKED',    'not passable'),
    },
    'cascade_tier': {
        0: ('BASELINE',   'no chain active'),
        1: ('MONITORING', 'partial signals on one chain'),
        2: ('WATCH',      'chain forming'),
        4: ('ACTIVE',     'chain operational'),
        5: ('COMPOUND',   'two or more chains at once'),
    },
    'chokepoint_status': {
        0: ('OPEN',       'transiting normally'),
        3: ('CONTESTED',  'transit under active threat'),
        4: ('DISRUPTED',  'transit materially interrupted'),
    },
    'gdacs_alert': {
        0: ('GREEN',      'routine event, negligible modelled impact'),
        2: ('ORANGE',     'significant modelled impact'),
        3: ('RED',        'severe modelled impact'),
    },
}


def families(ladder):
    """The sidebar structure: one headline per rung, member words beneath.

    Returns [] for an unknown ladder. A rank with no FAMILY_NAMES entry still
    appears, headlined by its own loudest rung -- a missing label degrades the
    presentation, it never drops the rung from the guide.
    """
    lad = LADDERS.get(ladder)
    if not lad:
        return []
    by_rank = {}
    for rung, meta in lad['rungs'].items():
        by_rank.setdefault(meta['rank'], []).append((rung, meta))
    out = []
    for rk in sorted(by_rank):
        members = sorted(by_rank[rk], key=lambda kv: kv[0])
        name, blurb = FAMILY_NAMES.get(ladder, {}).get(
            rk, (members[0][1]['display'], members[0][1]['means']))
        out.append({
            'rank': rk,
            'name': name,
            'blurb': blurb,
            'platform_level': members[0][1]['to_platform'],
            # The headline word is not repeated underneath itself.
            'also_called': [m[1]['display'] for m in members
                            if m[1]['display'] != name],
            'words': [{'rung': m[0], 'display': m[1]['display'], 'means': m[1]['means']}
                      for m in members],
        })
    return out


# Rungs carried on a provisional reading rather than a ruling. Surfaced in the
# payload so a provisional decision cannot quietly become a settled one.
PENDING_RULINGS = {
    'greece_vector_band': {
        'rupture': ('RAISED 6 Oct 2026, DECIDES: Rachel. Greece rung 5 is defined as '
                    '"Maximal -- kinetic, detente collapse, ambassadorial recall". A '
                    'kinetic exchange and a recalled ambassador are different events '
                    'with different consequences and one rung cannot report both. '
                    'SHOULD IT BE SPLIT -- diplomatic rupture at platform 4, kinetic at '
                    'platform 5 -- and what observable separates them? INTERIM: rungs 4 '
                    'and 5 both map to platform 4, so this ladder cannot emit platform '
                    '5. COST OF WAITING: a genuine Greece-Turkey kinetic incident '
                    'under-reads as Coercion rather than Active Conflict. That is the '
                    'safer of the two errors but it is still an error.'),
        'crisis':  ('Greece rank 3 is "Crisis"; the same word is rank 5 on '
                    'rhetoric_band. Mapped here to platform 3 on Greece\'s own '
                    'definition ("formal protest, incident, talks strain"), NOT on the '
                    'word. Flagged so the collision is visible rather than settled by '
                    'whichever table a caller happened to reach first.'),
    },
    'rhetoric_band': {
        'crisis':   'placed at rank 5 by Claude; not ruled on',
        'incident': 'placed at rank 4 by Claude (L4 armed incident); not ruled on',
        'low':      ('kept at rank 0, NOT promoted to MONITORING. Rachel grouped '
                     'low with none as "monitoring (or below heightened)"; rank 0 '
                     'is below heightened and matches both live tables, and a '
                     'measured-low is a real reading that rank 1 would overstate.'),
        'none':     ('treated as an ABSENCE, not a rung. "None" cannot be told '
                     'apart from "nothing was read", and the whole module exists '
                     'to stop an unread thing rendering as a quiet one. If it '
                     'genuinely means a measured zero, move it to rank 0.'),
    },
}


# Words that appear in more than one ladder with DIFFERENT answers. Listed so a
# caller that cannot name its ladder knows it has a real decision to make rather
# than a lookup to perform.
AMBIGUOUS_RUNGS = {}
for _lid, _lad in LADDERS.items():
    for _r in _lad['rungs']:
        AMBIGUOUS_RUNGS.setdefault(_r, []).append(_lid)
AMBIGUOUS_RUNGS = {r: sorted(ls) for r, ls in AMBIGUOUS_RUNGS.items()
                   if len({LADDERS[l]['rungs'][r]['to_platform'] for l in ls}) > 1}


# ════════════════════════════════════════════════════════════════════
# LOOKUPS -- every one returns None for an unrecognised rung, never 0
# ════════════════════════════════════════════════════════════════════

def _norm(rung):
    return str(rung or '').strip().lower().replace('-', '_').replace(' ', '_')


def is_absence(ladder, rung):
    """True when this rung means 'not read' rather than 'read as low'."""
    lad = LADDERS.get(ladder)
    return bool(lad) and _norm(rung) in lad.get('absence', ())


def rank(ladder, rung):
    """Ordering WITHIN a ladder. None when unrecognised or an absence."""
    lad = LADDERS.get(ladder)
    if not lad:
        return None
    r = lad['rungs'].get(_norm(rung))
    return r['rank'] if r else None


def to_platform(ladder, rung):
    """Translate a rung to the platform 0-6 ladder. None when unrecognised.

    None is the whole point. A caller that wants a floor must choose it in the
    open: `to_platform(...) or 0` is a visible decision; a dict default is not.
    """
    lad = LADDERS.get(ladder)
    if not lad:
        return None
    r = lad['rungs'].get(_norm(rung))
    return r['to_platform'] if r else None


def display(ladder, rung):
    """Display word for a rung. Falls back to the input upper-cased, so an
    unknown rung still renders as itself rather than vanishing."""
    lad = LADDERS.get(ladder)
    r = (lad or {}).get('rungs', {}).get(_norm(rung)) if lad else None
    return r['display'] if r else str(rung or '').upper()


def means(ladder, rung):
    lad = LADDERS.get(ladder)
    r = (lad or {}).get('rungs', {}).get(_norm(rung)) if lad else None
    return r['means'] if r else ''


def meets(ladder, rung, minimum):
    """Threshold test within one ladder. False when either side is unreadable --
    an unknown rung must not pass a gate by accident."""
    a, b = rank(ladder, rung), rank(ladder, minimum)
    return (a is not None and b is not None and a >= b)


def platform_display(level, axis=None):
    """'L4 Coercion' or, with an axis, 'L4 armed incident'."""
    try:
        lv = int(level)
    except (TypeError, ValueError):
        return 'UNREAD'
    if axis and axis in AXIS_MEANINGS:
        txt = AXIS_MEANINGS[axis]['rungs'].get(lv)
        if txt:
            return 'L%d %s' % (lv, txt)
    d = PLATFORM_LEVELS.get(lv, {}).get('display')
    return ('L%d %s' % (lv, d)) if d else 'L%d' % lv


def ladders():
    return sorted(LADDERS)


def describe(ladder):
    """Everything a UI guide needs about one instrument."""
    lad = LADDERS.get(ladder)
    if not lad:
        return None
    rungs = sorted(lad['rungs'].items(), key=lambda kv: kv[1]['rank'])
    return {
        'id': ladder, 'label': lad['label'], 'measures': lad['measures'],
        'source': lad['source'],
        'rungs': [{'rung': k, 'display': v['display'], 'rank': v['rank'],
                   'platform_level': v['to_platform'], 'means': v['means']}
                  for k, v in rungs],
        'absence_rungs': list(lad.get('absence', ())),
    }


def canon_payload():
    """The whole canon, shaped for /api/severity-canon so the page guide can be
    GENERATED rather than hand-written. A guide that is typed into HTML drifts
    from the arithmetic the moment either changes; one that renders from here
    cannot."""
    return {
        'version': __version__,
        'as_of': CANON_AS_OF,
        'platform_levels': [{'level': k, **v} for k, v in sorted(PLATFORM_LEVELS.items())],
        'axis_meanings': {k: {'label': v['label'],
                              'rungs': [{'level': lv, 'means': txt}
                                        for lv, txt in sorted(v['rungs'].items())]}
                          for k, v in AXIS_MEANINGS.items()},
        'ladders': [describe(l) for l in ladders()],
        # The sidebar renders from this: headline word large, synonyms small.
        'families': {l: families(l) for l in ladders()},
        'ambiguous_rungs': AMBIGUOUS_RUNGS,
        'pending_rulings': PENDING_RULINGS,
        'doctrine': (
            'A rung this module does not recognise returns None, never 0. A '
            'missing key must be loud. Levels are convergence readings of what '
            'is present, not forecasts of what follows.'
        ),
    }


# ════════════════════════════════════════════════════════════════════
# PARITY -- what WOULD change if a module adopted the canon
# ════════════════════════════════════════════════════════════════════

def parity_report(existing_table, ladder, table_name='(unnamed)'):
    """Compare a module's live translation table against the canon.

    Returns every input that would change answer, every input the canon does not
    know, and every rung the canon has that the table is missing -- that last
    category being how 'high' silently became 0 in the GPI for weeks.

    Nothing is migrated until this list has been read. Shipping the canon alone
    changes no behaviour anywhere.
    """
    agree, differ, canon_missing, table_missing = [], [], [], []
    for word, old in (existing_table or {}).items():
        new = to_platform(ladder, word)
        if new is None:
            canon_missing.append({'rung': word, 'table_says': old})
        elif new == old:
            agree.append(word)
        else:
            differ.append({'rung': word, 'table_says': old, 'canon_says': new})
    for word in LADDERS.get(ladder, {}).get('rungs', {}):
        if word not in (existing_table or {}):
            table_missing.append({'rung': word, 'canon_says': to_platform(ladder, word)})
    return {
        'table': table_name, 'ladder': ladder,
        'agree_count': len(agree),
        'would_change': differ,
        'unknown_to_canon': canon_missing,
        'missing_from_table': table_missing,
        'safe_to_migrate': not differ and not canon_missing,
        'note': ('`missing_from_table` is the dangerous column: those rungs hit '
                 'the table\'s default today. In _LEVEL_LABEL_MAP that default '
                 'was 0, which is how HIGH read as silence until Jun 18 2026.'),
    }


def resolve(rung, prefer=None):
    """Resolve a bare word with NO declared ladder -- the unavoidable case.

    _safe_level in the GPI receives a string and cannot know which instrument
    produced it. That is the ambiguity this module exists to name, and it cannot
    be wished away at a call site that genuinely does not know.

    So: walk the ladders in preference order, return the first hit, and SAY so.
    Returns (platform_level, ladder_used, was_ambiguous). platform_level is None
    when no ladder recognises the word -- never 0.

    `was_ambiguous` is True when more than one ladder knows the word and they
    disagree. A caller that logs those is a caller that can see how often the
    platform is guessing, which is the point.
    """
    order = tuple(prefer or LADDER_PREFERENCE)
    hits = [l for l in order if to_platform(l, rung) is not None]
    if not hits:
        return (None, None, False)
    levels = {to_platform(l, rung) for l in hits}
    return (to_platform(hits[0], rung), hits[0], len(levels) > 1)


# Rhetoric first: most signals reaching the GPI are rhetoric-tracker signals
# carrying band words, and for the words that overlap (elevated, high, active)
# the rhetoric reading is the LOWER one -- which is the direction Rachel ruled
# for on Oct 6, so that L5 and L6 keep meaning something.
#
# The cost is real and worth stating: a COMMODITY signal arriving as a bare
# 'elevated' now reads L2 rather than L3. Any call site that knows it is holding
# a commodity reading should pass ladder='commodity_alert' explicitly rather than
# rely on this order.
LADDER_PREFERENCE = ('rhetoric_band', 'commodity_alert', 'chokepoint_status',
                     'cascade_tier', 'corridor_state', 'gdacs_alert')


def register_severity_canon_endpoints(app):
    """Serve the canon so the page guide renders FROM it.

    Flask is imported inside the function, matching corridor_dependence.py, so
    this module stays importable with no web framework present and deploys
    byte-identical to every backend.
    """
    from flask import jsonify

    @app.route('/api/severity-canon', methods=['GET', 'OPTIONS'])
    def severity_canon_all():
        return jsonify(canon_payload()), 200

    @app.route('/api/severity-canon/<ladder_id>', methods=['GET'])
    def severity_canon_one(ladder_id):
        d = describe((ladder_id or '').strip().lower())
        if not d:
            return jsonify({'success': False,
                            'error': "no ladder '%s'" % ladder_id,
                            'known': ladders()}), 404
        d['families'] = families(ladder_id)
        return jsonify(d), 200

    print('[Severity Canon] endpoints registered (/api/severity-canon) v%s' % __version__)


# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('severity_canon v%s (as of %s)\n' % (__version__, CANON_AS_OF))

    assert to_platform('commodity_alert', 'elevated') == 3
    assert to_platform('rhetoric_band',   'elevated') == 2
    print('SAME WORD, DIFFERENT INSTRUMENT -- both correct:')
    print('  commodity_alert:elevated -> platform %s' % to_platform('commodity_alert', 'elevated'))
    print('  rhetoric_band:elevated   -> platform %s\n' % to_platform('rhetoric_band', 'elevated'))

    assert to_platform('commodity_alert', 'banana') is None
    assert rank('commodity_alert', 'banana') is None
    assert meets('commodity_alert', 'banana', 'elevated') is False
    print('UNKNOWN RUNG -> None, and fails a threshold rather than passing it\n')

    assert is_absence('corridor_state', 'unknown') is True
    assert to_platform('corridor_state', 'unknown') is None
    print('ABSENCE -> None, never a low reading\n')

    assert meets('commodity_alert', 'high', 'elevated') is True
    assert meets('commodity_alert', 'monitor', 'elevated') is False
    print('THRESHOLDS hold within a ladder\n')

    print('AMBIGUOUS WORDS (same word, different answer per instrument):')
    for w, ls in sorted(AMBIGUOUS_RUNGS.items()):
        print('  %-10s %s' % (w, ', '.join('%s->%s' % (l, to_platform(l, w)) for l in ls)))

    print('\nPARITY vs the live GPI table:')
    LIVE_GPI = {'surge': 5, 'critical': 5, 'crisis': 5, 'high': 4, 'incident': 4,
                'elevated': 3, 'heightened': 3, 'warning': 3, 'alert': 3,
                'active': 2, 'rising': 2, 'tensions': 2, 'normal': 1,
                'stable': 1, 'baseline': 1, 'low': 0, 'monitoring': 0, 'none': 0}
    rep = parity_report(LIVE_GPI, 'commodity_alert', '_LEVEL_LABEL_MAP')
    print('  agree: %d   would change: %d   unknown to canon: %d   missing from table: %d'
          % (rep['agree_count'], len(rep['would_change']),
             len(rep['unknown_to_canon']), len(rep['missing_from_table'])))
    for d in rep['would_change']:
        print('    CHANGES  %-10s %s -> %s' % (d['rung'], d['table_says'], d['canon_says']))
    for d in rep['missing_from_table']:
        print('    MISSING  %-10s canon says %s (hits the default today)'
              % (d['rung'], d['canon_says']))

    print('\nSELF-TEST COMPLETE')
