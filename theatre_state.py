"""
Asifah Analytics -- THEATRE STATE VOCABULARY
v1.0.0 -- October 3 2026  |  portable, drop into any backend

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════
An analyst landing on the Middle East BLUF reads:

    "Regional posture at ELEVATED, with peak escalation L4 across 6 live
     trackers. The most volatile theater is Israel (composite L4, rising)."

They then click into Israel and read "ISRAEL inbound from Iran L4", and go
up to the GPI and read "Unity of Fronts is elevated (L4)". The same number,
three times, never once explained. L4 is legible to us and to nobody else.

This vocabulary already existed. global_pressure_index.py defined
THEATRE_STATE in July 2026, with the reasoning written out in full, and then
called it in exactly ONE place -- the landing-page banner. Thirty narrative
functions below it, the whole ME regional BLUF, and every tracker long_text
kept emitting raw levels. This module promotes that vocabulary to a shared
primitive so there is one place to fix it and one vocabulary to tune.

THE RULE
═══════════════════════════════════════════════════════════════════════
    The state phrase LEADS. The level follows in parentheses.

        BAD   "Iran L5"
        GOOD  "Iran on an active war footing (L5)"

The number is not deleted -- it is a real datum, it is how we talk to each
other, and the UI chips are backed by a legend. It just stops being the
first thing a stranger has to decode.

WHY AXIS-AWARE, NOT ONE TABLE
═══════════════════════════════════════════════════════════════════════
(Reasoning inherited from the GPI original, preserved because it is right.)

The platform models four pressure axes. A single level-only vocabulary
collapses them, and collapses them WRONGLY: a magnitude-9 earthquake that
kills thousands is a legitimate L5, but calling it "active war footing" is
not imprecise, it is FALSE. Tohoku 2011 is the reference case -- exogenous,
mass-casualty, no kinetic content whatsoever. The page must be able to say
"mass-casualty humanitarian disaster" without implying a war.

DESIGNED FOR PEACETIME, DELIBERATELY
═══════════════════════════════════════════════════════════════════════
The global level has sat high for so long that the low bands are untested,
so they are written to be INFORMATIVE on the way down. If Iran fell to L2,
"pressure building" is a real read; "L2" is not. A vocabulary that only
works during a war is a vocabulary that cannot report peace.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

__version__ = '1.0.0'

PRESSURE_KINETIC      = 'kinetic'
PRESSURE_ECONOMIC     = 'economic'
PRESSURE_HUMANITARIAN = 'humanitarian'
PRESSURE_DIPLOMATIC   = 'diplomatic'

THEATRE_STATE = {
    'kinetic': {
        0: 'quiet',
        1: 'rhetorical signalling',
        2: 'pressure building',
        3: 'standoff hardening',
        4: 'armed incident',
        5: 'active war footing',
        6: 'red line breached',
    },
    'humanitarian': {
        0: 'quiet',
        1: 'early humanitarian indicators',
        2: 'population pressure building',
        3: 'humanitarian conditions deteriorating',
        4: 'acute humanitarian emergency',
        5: 'mass-casualty humanitarian disaster',
        6: 'catastrophic humanitarian collapse',
    },
    'economic': {
        0: 'quiet',
        1: 'market signalling',
        2: 'cost pressure building',
        3: 'supply pressure hardening',
        4: 'acute supply disruption',
        5: 'economic rupture',
        6: 'systemic economic breakdown',
    },
    'diplomatic': {
        0: 'quiet',
        1: 'diplomatic signalling',
        2: 'diplomatic friction',
        3: 'diplomatic standoff',
        4: 'talks collapsed',
        5: 'diplomatic rupture',
        6: 'relations severed',
    },
}

# Category overrides. Some signals describe a MECHANISM that the level and
# axis together still cannot convey -- a hub losing ground is not "an armed
# incident" even at L4, and a fuel blockade is not "acute supply disruption"
# when the point is that a CAPITAL is being strangled.
CATEGORY_STATE = {
    'hub_trajectory':            'network position shifting',
    'economic_siege':            'capital under economic siege',
    'client_hedging':            'patron dependency loosening',
    'insurgent_convergence':     'insurgent factions converging',
    'claiming_actor_silence':    'unusual quiet from a claiming actor',
    'silence_anomaly':           'unusual quiet from an actor that normally speaks',
    'diplomatic_track_active':   'negotiation track running',
    'diplomatic_active':         'negotiation track running',
    'green_line_active':         'de-escalation channel open',
    'mediation_active':          'mediation underway',
    'multi_axis_convergence':    'multiple fronts moving together',
    'dual_chokepoint':           'two shipping chokepoints under pressure',
    # v1.0.0 (Oct 3 2026) -- Palestinian financial access. 'acute supply
    # disruption' is the economic-axis phrase for L4 and it is wrong here:
    # nothing is being disrupted in transit. The mechanism is access to the
    # payment system itself.
    'financial_access_stress':   'payment and payroll access under strain',
}

# Which axis a category belongs to, when the caller does not say.
CATEGORY_AXIS_HINTS = {
    'humanitarian': 'humanitarian', 'humanitarian_lebanon': 'humanitarian',
    'displacement': 'humanitarian', 'migration': 'humanitarian',
    'health_emergency': 'humanitarian', 'famine_risk': 'humanitarian',
    'economic_siege': 'economic', 'logistics_corridor': 'economic',
    'market_fragility': 'economic', 'commodity_pressure': 'economic',
    'commodity': 'economic', 'economic_stress': 'economic', 'oil': 'economic',
    'financial_access_stress': 'economic',
    'diplomatic_track': 'diplomatic', 'mediation': 'diplomatic',
    'mediation_active': 'diplomatic', 'ceasefire': 'diplomatic',
    'kinetic_tempo': 'kinetic', 'red_line_breached': 'kinetic',
    'kinetic_pressure': 'kinetic', 'theatre_high': 'kinetic',
}


def theatre_state(level, category=None, pressure_type=None):
    """Plain-language state phrase, resolved by AXIS then level.

    Resolution order, most-specific first:
      1. category override -- the mechanism, where it says more than either
      2. axis + level      -- the normal path
      3. kinetic + level   -- last resort, matching the platform default
    """
    if category and category in CATEGORY_STATE:
        return CATEGORY_STATE[category]
    axis = (pressure_type or CATEGORY_AXIS_HINTS.get(category or '')
            or PRESSURE_KINETIC)
    if axis not in THEATRE_STATE:
        axis = PRESSURE_KINETIC
    try:
        lv = max(0, min(6, int(level or 0)))
    except (TypeError, ValueError):
        lv = 0
    return THEATRE_STATE[axis][lv]


def state_with_level(level, category=None, pressure_type=None, upper=False):
    """The canonical reader-facing form: phrase first, number in parentheses.

        state_with_level(5)                      -> 'active war footing (L5)'
        state_with_level(4, 'humanitarian')      -> 'acute humanitarian emergency (L4)'
        state_with_level(3, pressure_type='economic') -> 'supply pressure hardening (L3)'

    Use this anywhere a human reads a sentence. Use a bare level only in a
    chip or pill that sits next to a legend.
    """
    phrase = theatre_state(level, category, pressure_type)
    try:
        lv = max(0, min(6, int(level or 0)))
    except (TypeError, ValueError):
        lv = 0
    if upper:
        phrase = phrase.upper()
    return '%s (L%d)' % (phrase, lv)


def named_state(name, level, category=None, pressure_type=None):
    """'Israel -- active war footing (L5)' -- for naming a theatre inline.

    DELIBERATELY the dash form rather than an inflected sentence. The first
    draft of this tried to pick 'on a' / 'on an' and produced "Oman on a talks
    collapsed (L4)", because the vocabulary mixes noun phrases ('armed
    incident') with clauses ('talks collapsed') and no article rule survives
    both. Inflecting English from a lookup table is a losing game; the dash is
    always grammatical and reads like an intelligence product rather than like
    a sentence a machine assembled.
    """
    phrase = theatre_state(level, category, pressure_type)
    try:
        lv = max(0, min(6, int(level or 0)))
    except (TypeError, ValueError):
        lv = 0
    return '%s -- %s (L%d)' % (name, phrase, lv)


if __name__ == '__main__':
    print('Theatre State v%s -- self-test\n' % __version__)

    print('TEST 1 -- the Tohoku case: L5 is not a war')
    assert theatre_state(5, pressure_type='humanitarian') == 'mass-casualty humanitarian disaster'
    assert theatre_state(5, pressure_type='kinetic') == 'active war footing'
    print('  humanitarian L5 -> %s' % theatre_state(5, pressure_type='humanitarian'))
    print('  kinetic      L5 -> %s\n' % theatre_state(5, pressure_type='kinetic'))

    print('TEST 2 -- category override beats axis+level')
    assert theatre_state(4, category='financial_access_stress') == 'payment and payroll access under strain'
    print('  financial_access_stress L4 -> %s\n' % theatre_state(4, category='financial_access_stress'))

    print('TEST 3 -- category implies axis when caller is silent')
    assert theatre_state(3, category='humanitarian') == 'humanitarian conditions deteriorating'
    print('  humanitarian L3 -> %s\n' % theatre_state(3, category='humanitarian'))

    print('TEST 4 -- unknown axis falls back to kinetic, never raises')
    assert theatre_state(4, pressure_type='nonsense') == 'armed incident'
    assert theatre_state(None) == 'quiet'
    assert theatre_state('x') == 'quiet'
    assert theatre_state(99) == 'red line breached'
    assert theatre_state(-3) == 'quiet'
    print('  bad input never raises\n')

    print('TEST 5 -- the reader-facing forms')
    print('  %s' % state_with_level(5))
    print('  %s' % state_with_level(4, pressure_type='humanitarian'))
    print('  %s' % named_state('Israel', 5))
    print('  %s' % named_state('Lebanon', 3))
    print('  %s' % named_state('Oman', 4, pressure_type='diplomatic'))
    print('  %s' % named_state('Qatar', 0))
    assert named_state('Israel', 5) == 'Israel -- active war footing (L5)'
    assert named_state('Lebanon', 3) == 'Lebanon -- standoff hardening (L3)'
    assert named_state('Qatar', 0) == 'Qatar -- quiet (L0)'
    # the regression that produced "Oman on a talks collapsed"
    assert named_state('Oman', 4, pressure_type='diplomatic') == 'Oman -- talks collapsed (L4)'
    print()

    print('TEST 6 -- peacetime bands say something real')
    for lv in range(0, 4):
        assert theatre_state(lv) not in ('', None)
    print('  L0-L3 kinetic: %s' % ', '.join(theatre_state(l) for l in range(4)))
    print()

    print('ALL THEATRE STATE TESTS PASSED')
