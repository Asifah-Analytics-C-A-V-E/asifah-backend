"""
framework_gates.py -- Asifah Analytics -- SHARED MODULE -- v1.0.0 Aug 2026
============================================================================
Generalised gate-ladder primitive for negotiated frameworks.

WHY THIS IS SHARED, and why it was worth generalising: the Lebanon Trilateral
Framework (26 Jun 2026) and the Gaza Board of Peace Roadmap (30 Jul 2026) have
structurally identical failure modes.

    stage                  Lebanon                      Gaza
    ---------------------  ---------------------------  ---------------------------
    framework signed       Trilateral, 26 Jun           BoP Roadmap, 30 Jul
    disarmament gate       Hizballah will not           Hamas "accepts in principle",
                                                        hands over nothing
    verification body      third-party verifier ABSENT  IVC has not certified
    downstream blocked     aid, zone expansion          IDF withdrawal, NCAG entry,
                                                        ISF deployment
    sequencing standoff    LAF deploys, does not clear  no withdrawal before
                                                        disarmament vs no disarmament
                                                        before statehood

THE MEASUREMENT: a DECLARED-vs-ACTUAL SPREAD. Every gate has an announcement
and a verification, and in a stalled framework they come apart. "LAF deployed"
is declared and true; "weapons handed over" is not happening. "Agreement
reached" is declared; "ISF deployed" is 200 people with no timeframe. A high
declared count against a zero actual count at the same gate IS the stall
signature, and unlike "the process is going badly" it is machine-readable.

THE FREEZE COUPLING is the reason Slice 1 existed. A stall reads completely
differently depending on whether the other party is CAPABLE of deciding:

    stalled, no freeze   -> FAILING.  The parties are not delivering.
    stalled, freeze on   -> PARKED.   No Israeli government is positioned to
                                      conclude anything; the framework is
                                      waiting, not dying.
    stalled, freeze overrun -> PARKED, but the park is itself overrunning,
                                      which is a third condition.

Without that distinction the platform calls a dying process when it is a
waiting one -- the single most consequential misread available here.

DOCTRINE: reports WHICH gate is blocking and how the stall should be read.
Does NOT forecast whether a framework succeeds. Outcome is not ours to call.

DEPLOYMENT: shared module, byte-identical across backends that use it.
Currently ME only (Lebanon + Gaza both read there). md5 parity applies.
"""

import os
import json
import requests
from datetime import datetime, timezone

__version__ = '1.0.0'

UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_REST_URL')
               or os.environ.get('UPSTASH_REDIS_URL', '')).rstrip('/')
UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_REST_TOKEN')
                 or os.environ.get('UPSTASH_REDIS_TOKEN', ''))

ELECTION_STATE_KEY = 'israel:election_cycle:state'

# States in which large external decisions do not get made. Mirrors
# israel_stability.FREEZE_STATES; duplicated deliberately so this module has no
# import dependency on a tracker and stays deployable on any backend.
FREEZE_STATES = {'dissolution', 'campaign', 'voted', 'formation'}
PARTIAL_FREEZE_STATES = {'coalition_crisis'}


def _redis_get(key):
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None
    try:
        r = requests.get(f'{UPSTASH_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'},
                         timeout=(5, 10))
        if r.status_code == 200:
            raw = r.json().get('result')
            if raw:
                return json.loads(raw)
    except Exception as e:
        print(f'[Framework Gates] Redis GET failed ({e})')
    return None


# ============================================================================
# FRAMEWORK REGISTRY
# ============================================================================
# Each framework declares its gates in SEQUENCE ORDER. Order is load-bearing:
# a block at an upstream gate holds everything downstream regardless of
# activity there, so the FIRST blocked gate is the finding.
#
# declared = announced, asserted, pledged, intended
# actual   = observed, verified, delivered, handed over

FRAMEWORK_REGISTRY = {

    'lebanon_trilateral': {
        'label': 'Trilateral Framework',
        'signed': '2026-06-26',
        'gate_order': ['clearance', 'verification', 'aid_flow', 'zone_expansion'],
        'gates': {
            'clearance': {
                'label': 'Clearance of fighters & weapons',
                'declared': [
                    'laf deployed', 'army deployed south', 'laf takes control',
                    'laf assumes control', 'army control south litani',
                    'checkpoints established', 'laf checkpoints', 'army positions',
                    'الجيش انتشر', 'انتشار الجيش', 'حواجز الجيش',
                    'צה"ל נסוג', 'הצבא הלבנוני נפרס',
                ],
                'actual': [
                    'weapons handed over', 'handover of weapons', 'weapons cache seized',
                    'arms cache found', 'tunnels destroyed', 'tunnel network cleared',
                    'rockets confiscated', 'launchers seized', 'disarmament completed',
                    'hezbollah withdrew from', 'fighters withdrew',
                    'تسليم السلاح', 'مصادرة أسلحة', 'تدمير الأنفاق', 'ضبط مخزن أسلحة',
                    'פירוק נשק', 'תפיסת אמצעי לחימה', 'הריסת מנהרות',
                ],
            },
            'verification': {
                'label': 'Third-party verification',
                'declared': [
                    'verification mechanism', 'third-party verifier', 'third party verifier',
                    'monitoring mechanism', 'verification body', 'observers proposed',
                    'verifier discussed', 'monitoring committee',
                    'آلية التحقق', 'طرف ثالث', 'لجنة المراقبة',
                    'מנגנון אימות', 'גורם מאמת',
                ],
                'actual': [
                    'verifier appointed', 'verification team deployed', 'observers deployed',
                    'monitors arrived', 'verification mission began', 'inspectors deployed',
                    'certified cleared', 'verified clearance',
                    'تعيين المراقبين', 'وصول المراقبين', 'بدء مهمة التحقق',
                    'פריסת משקיפים',
                ],
            },
            'aid_flow': {
                'label': 'Aid & reconstruction flow',
                'declared': [
                    'aid pledged', 'reconstruction funds pledged', 'donors pledged',
                    'reconstruction plan', 'funds allocated', 'aid package announced',
                    'world bank loan', 'reconstruction conference',
                    'تعهدات المانحين', 'خطة إعادة الإعمار', 'مساعدات موعودة',
                ],
                'actual': [
                    'aid delivered', 'reconstruction began', 'rebuilding started',
                    'funds disbursed', 'first convoy', 'construction under way',
                    'homes rebuilt', 'compensation paid',
                    'وصول المساعدات', 'بدء إعادة الإعمار', 'صرف الأموال',
                ],
            },
            'zone_expansion': {
                'label': 'Pilot zone expansion',
                'declared': [
                    'expand pilot zone', 'additional zones', 'second pilot zone',
                    'next phase', 'extend the model', 'more villages',
                    'توسيع المنطقة', 'مرحلة ثانية', 'مناطق إضافية',
                ],
                'actual': [
                    'second zone established', 'new zone activated', 'zone expanded to',
                    'additional villages transferred', 'phase two began',
                    'تفعيل منطقة جديدة', 'تسليم قرى إضافية',
                ],
            },
        },
    },

    # Gaza: Board of Peace Roadmap, announced 30 Jul 2026, implementing the
    # 20-point plan endorsed by UNSCR 2803 (17 Nov 2025). Sequence per the
    # published roadmap: framework acceptance -> timetable within 14 days ->
    # NCAG enters -> staged disarmament (police weapons first, then heavy
    # weapons) -> IVC certifies -> ISF deploys and trains a Palestinian police
    # force -> Israeli withdrawal. Withdrawal is explicitly LAST: the Board of
    # Peace stated there is no withdrawal before disarmament is complete.
    'gaza_bop': {
        'label': 'Board of Peace Roadmap',
        'signed': '2026-07-30',
        'gate_order': ['disarmament', 'verification', 'isf_deployment',
                       'withdrawal', 'reconstruction'],
        'gates': {
            'disarmament': {
                'label': 'Hamas disarmament',
                'declared': [
                    'hamas agrees to disarm', 'disarmament agreement', 'accepts the framework',
                    'agreed to a document', 'disarmament roadmap', 'roadmap agreed',
                    'hamas accepts in principle', 'factions agreed', 'historic agreement',
                    'اتفاق نزع السلاح', 'حماس توافق', 'خارطة الطريق',
                    'הסכם פירוז', 'חמאס מסכימה',
                ],
                'actual': [
                    'weapons handed over', 'handover of weapons', 'weapons decommissioned',
                    'heavy weapons surrendered', 'police weapons transferred',
                    'arms surrendered to', 'decommissioning began', 'disarmament began',
                    'تسليم الأسلحة', 'بدء نزع السلاح', 'تسليم الأسلحة الثقيلة',
                    'מסירת נשק', 'פירוק נשק בפועל',
                ],
            },
            'verification': {
                'label': 'IVC certification',
                'declared': [
                    'international verification committee', 'ivc', 'verification committee',
                    'independent body will verify', 'verification mechanism gaza',
                    'لجنة التحقق الدولية', 'آلية التحقق',
                ],
                'actual': [
                    'ivc certified', 'verification committee certified', 'certified compliance',
                    'independently verified', 'verification completed gaza',
                    'صادقت لجنة التحقق', 'تم التحقق',
                ],
            },
            'isf_deployment': {
                'label': 'ISF deployment',
                'declared': [
                    'international stabilization force', 'international stabilisation force',
                    'isf will deploy', 'israel approved isf', 'isf entry approved',
                    'stabilization force approved', 'friendly countries contribute',
                    'قوة الاستقرار الدولية',
                    'כוח הייצוב הבינלאומי',
                ],
                'actual': [
                    'isf deployed', 'isf troops arrived', 'stabilization force entered',
                    'isf began operations', 'palestinian police trained',
                    'new police force deployed', 'ncag entered', 'ncag assumed',
                    'national committee entered',
                    'وصول قوة الاستقرار', 'دخول اللجنة الوطنية',
                ],
            },
            'withdrawal': {
                'label': 'Israeli withdrawal',
                'declared': [
                    'israel will withdraw', 'withdrawal agreed', 'phased withdrawal gaza',
                    'idf to pull back', 'withdrawal timetable',
                    'انسحاب إسرائيلي', 'جدول الانسحاب',
                    'נסיגה מעזה',
                ],
                'actual': [
                    'idf withdrew from', 'troops pulled back from', 'withdrawal completed',
                    'israel withdrew from gaza', 'forces left gaza',
                    'انسحبت القوات', 'اكتمل الانسحاب',
                    'צה"ל נסוג מעזה',
                ],
            },
            'reconstruction': {
                'label': 'Reconstruction',
                'declared': [
                    'reconstruction plan gaza', 'rebuilding gaza', 'donors pledged gaza',
                    'reconstruction conference gaza', 'gaza recovery plan',
                    'إعادة إعمار غزة', 'مؤتمر المانحين',
                ],
                'actual': [
                    'reconstruction began gaza', 'rebuilding started gaza',
                    'materials entered gaza', 'construction under way gaza',
                    'homes rebuilt gaza', 'rubble cleared',
                    'بدء الإعمار', 'دخول مواد البناء',
                ],
            },
        },
    },
}


# ============================================================================
# FREEZE READING
# ============================================================================

def read_freeze_state():
    """Israeli electoral-cycle stage, written by israel_stability._detect_election_state.

    Absence-honest: if the key is missing the freeze is UNKNOWN, not False.
    Assuming 'no freeze' when we simply cannot see would silently restore the
    exact misread this coupling exists to prevent.
    """
    st = _redis_get(ELECTION_STATE_KEY) or {}
    state = st.get('state')
    if not state:
        return {'known': False, 'state': None, 'freeze': None, 'partial': None}
    return {
        'known': True,
        'state': state,
        'freeze': state in FREEZE_STATES,
        'partial': state in PARTIAL_FREEZE_STATES,
        'since': st.get('since'),
    }


# ============================================================================
# EVALUATION
# ============================================================================

def evaluate_gates(framework_id, articles, freeze=None, min_declared=2):
    """Gate ladder for one framework, with the stall read against the freeze.

    Args:
        framework_id: key in FRAMEWORK_REGISTRY
        articles:     list of {'title','description'} dicts
        freeze:       optional pre-read freeze dict; read from Redis if omitted
        min_declared: declared hits required before a zero-actual gate counts
                      as BLOCKED rather than quiet

    Returns a state dict. Never raises on unknown framework_id.
    """
    spec = FRAMEWORK_REGISTRY.get(framework_id)
    if not spec:
        return {'framework': framework_id, 'state': 'unknown',
                'note': 'Framework id not registered.', 'gates': {}}

    def _blob(a):
        return ((a.get('title') or '') + ' ' + (a.get('description') or '')).lower()

    def _count(triggers):
        n, hits = 0, []
        for a in (articles or []):
            b = _blob(a)
            m = [t for t in triggers if t.lower() in b]
            if m:
                n += 1
                hits.append(m[0])
        return n, hits[:3]

    gates = {}
    for gate_id in spec['gate_order']:
        g = spec['gates'][gate_id]
        dec, dec_hits = _count(g['declared'])
        act, act_hits = _count(g['actual'])
        gates[gate_id] = {
            'label': g['label'],
            'declared': dec,
            'actual': act,
            'spread': dec - act,
            'declared_examples': dec_hits,
            'actual_examples': act_hits,
            # Silence on BOTH sides is 'quiet', never 'blocked'. A quiet week is
            # no information; calling it a block would manufacture a finding.
            'state': ('blocked' if (dec >= min_declared and act == 0) else
                      'moving' if act > 0 else 'quiet'),
        }

    blocking = next((g for g in spec['gate_order']
                     if gates[g]['state'] == 'blocked'), None)
    moving = [g for g in spec['gate_order'] if gates[g]['state'] == 'moving']

    if freeze is None:
        freeze = read_freeze_state()

    if blocking:
        state = 'stalled'
        g = gates[blocking]
        headline = ('%s stalled at %s: %d declared, %d verified'
                    % (spec['label'], g['label'].lower(), g['declared'], g['actual']))
    elif moving:
        state = 'advancing'
        headline = ('%s advancing at %s'
                    % (spec['label'], ', '.join(gates[m]['label'].lower() for m in moving)))
    else:
        state = 'quiet'
        headline = 'No %s implementation signals this cycle' % spec['label']

    # ── The freeze reading: same stall, different finding ──
    freeze_reading, freeze_note = 'not_applicable', ''
    if state == 'stalled':
        if not freeze.get('known'):
            freeze_reading = 'unknown'
            freeze_note = ('Israeli electoral-cycle state is UNAVAILABLE this cycle, so whether '
                           'this stall is substantive or structural cannot be determined here. '
                           'That gap is surfaced rather than resolved by assumption. ')
        elif freeze.get('freeze'):
            freeze_reading = 'parked'
            freeze_note = ('READ AS PARKED, NOT FAILING. Israel is at the "%s" stage of its '
                           'electoral cycle, during which no government is positioned to '
                           'conclude an agreement of this kind. A stall in this window is '
                           'evidence about Israeli decision-making CAPACITY, not about either '
                           'party\'s willingness. The same gate readings outside a freeze would '
                           'support the opposite conclusion. ' % freeze.get('state'))
        elif freeze.get('partial'):
            freeze_reading = 'constrained'
            freeze_note = ('Israeli coalition survival is contested, which narrows what is '
                           'politically available without stopping decisions outright. This '
                           'stall is partly substantive and partly structural; the two cannot '
                           'be cleanly separated from open sources. ')
        else:
            freeze_reading = 'substantive'
            freeze_note = ('No Israeli decision freeze is in effect, so this stall is NOT '
                           'explained by an absent counterparty. On the evidence available the '
                           'blockage is substantive: the gate is being announced and not '
                           'delivered while both sides are capable of acting. ')

    note = ''
    if state == 'stalled':
        note = ('The blocking gate is being ANNOUNCED but not VERIFIED. That spread is the '
                'measurement. Because %s sits upstream in this sequence, a block there holds '
                'everything downstream regardless of activity below it. '
                % gates[blocking]['label'].lower())
    elif state == 'quiet':
        note = ('Absence of implementation reporting is NOT evidence of progress or of failure. '
                'Quiet cycles are ordinary. ')
    note += freeze_note
    note += ('This is a CONVERGENCE indicator, NOT a probability of action. Which gate is '
             'blocking is observable; whether the framework holds is not.')

    return {
        'framework': framework_id,
        'framework_label': spec['label'],
        'signed': spec.get('signed'),
        'state': state,
        'headline': headline,
        'blocking_gate': blocking,
        'blocking_gate_label': gates[blocking]['label'] if blocking else None,
        'moving_gates': moving,
        'gates': gates,
        'gate_order': spec['gate_order'],
        'freeze': freeze,
        'freeze_reading': freeze_reading,
        'note': note,
        'version': __version__,
    }


def list_frameworks():
    return {k: v['label'] for k, v in FRAMEWORK_REGISTRY.items()}
