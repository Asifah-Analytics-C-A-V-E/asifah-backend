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

__version__ = '1.0.0'
CANON_AS_OF = '2026-10-06'


# ════════════════════════════════════════════════════════════════════
# THE PLATFORM LADDER -- the one every other ladder translates INTO
# ════════════════════════════════════════════════════════════════════
# 0-6. This is the ladder the GPI publishes, the regional BLUFs carry, and the
# "How to read this" box on the pages explains. Its rungs mean different things
# on different axes, which is why each axis gets its own wording below.

PLATFORM_LEVELS = {
    0: {'key': 'quiet',    'display': 'L0 QUIET'},
    1: {'key': 'signal',   'display': 'L1 SIGNAL'},
    2: {'key': 'building', 'display': 'L2 BUILDING'},
    3: {'key': 'hardening','display': 'L3 HARDENING'},
    4: {'key': 'acute',    'display': 'L4 ACUTE'},
    5: {'key': 'rupture',  'display': 'L5 RUPTURE'},
    6: {'key': 'breached', 'display': 'L6 RED LINE BREACHED'},
}

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
            'alignment':  {'rank': 0, 'display': 'ALIGNMENT',  'to_platform': 0, 'means': 'positions converged, no friction'},
            'low':        {'rank': 0, 'display': 'LOW',        'to_platform': 0, 'means': 'minimal'},
            'simmering':  {'rank': 2, 'display': 'SIMMERING',  'to_platform': 2, 'means': 'sustained low heat'},
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
            'rupture':    {'rank': 4, 'display': 'RUPTURE',    'to_platform': 4, 'means': 'relationship broken'},
            'surge':      {'rank': 5, 'display': 'SURGE',      'to_platform': 5, 'means': 'peak'},
            'conflict':   {'rank': 5, 'display': 'CONFLICT',   'to_platform': 5, 'means': 'fighting'},
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
    """'L4 ACUTE' or, with an axis, 'L4 armed incident'."""
    try:
        lv = int(level)
    except (TypeError, ValueError):
        return 'UNREAD'
    if axis and axis in AXIS_MEANINGS:
        txt = AXIS_MEANINGS[axis]['rungs'].get(lv)
        if txt:
            return 'L%d %s' % (lv, txt)
    return PLATFORM_LEVELS.get(lv, {}).get('display', 'L%d' % lv)


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
        'ambiguous_rungs': AMBIGUOUS_RUNGS,
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
