"""
us_voice_signals.py -- Asifah Analytics -- SHARED MODULE -- v1.0.0 Aug 2026
============================================================================
Differential signal value of US envoy statements.

THE PRINCIPLE: signal value is inversely proportional to EXPECTEDNESS.

The platform already tracks Tom Barrack across several theatres, but it counts
his statements rather than weighing them, and counting is the wrong operation
here. A statement carries information in proportion to how UNUSUAL it is for
the person making it:

  Issa pressing on Hizballah disarmament ......... baseline. Near-zero signal.
  Huckabee defending Israeli settlement policy ... baseline. Near-zero signal.
  Barrack calling an Israeli strike escalatory ... DEVIATION. High signal.
  Huckabee criticising settler violence .......... DEVIATION. Highest signal
                                                   available in this registry.

That last one is the reason the module exists. Huckabee is the US voice most
publicly sympathetic to the settlement movement. When HE says settler violence
has gone too far, the information is not in the criticism -- criticism of
settler violence is abundant and cheap from other sources -- it is in WHO IS
MAKING IT. A friendly voice paying a cost to criticise is evidence; a hostile
voice criticising for free is not.

This generalises the ally-constraint multiplier built for the Syria/Amman
de-escalation ladder, where criticism from the striking party's own principal
ally was scored differently from adversary condemnation. Same primitive,
applied to named speakers rather than to states.

MEASUREMENT: each voice is scored against ITS OWN baseline, not against a
neutral centre. This is the tempo_baseline discipline pointed at speakers.

WHAT THIS MODULE WILL NOT DO: it does not characterise anyone's private
beliefs. `expected_posture` records PUBLICLY STATED positions and documented
institutional role, with the basis noted. A speaker's posture is a fact about
the public record, not a judgement about the person.

DEPLOYMENT: shared module, byte-identical across backends that use it.
"""

import re
from datetime import datetime, timezone

__version__ = '1.0.0'


# ============================================================================
# VOICE REGISTRY
# ============================================================================
# signal_mode            : 'valence' or 'presence'
# expected_posture       : what this speaker routinely says, per the public record
# posture_basis          : where that characterisation comes from
# informative_deviation  : which direction of departure carries signal, and why
# subjects               : entities whose treatment we score
#
# TWO SIGNAL MODES, because envoys and principals are not the same instrument:
#
#   'valence'  -- ambassadors speak constantly, so their baseline is dense and
#                 a DEPARTURE from it is the finding. Huckabee criticising
#                 settlers. Issa criticising Israel.
#
#   'presence' -- principals speak rarely and usually only at decision points,
#                 so there is no dense baseline to depart from. THE FACT THAT
#                 THEY SPOKE AT ALL is the finding, and its direction is
#                 secondary. Applying valence logic to a rare speaker would
#                 mean waiting for a deviation from a baseline that does not
#                 exist -- and missing the signal entirely.

US_VOICE_REGISTRY = {

    'barrack': {
        'signal_mode': 'valence',
        'display': 'Amb. Tom Barrack',
        'role': 'US Special Envoy for Syria; US Ambassador to Turkey',
        'portfolio': ['syria', 'lebanon', 'turkey', 'israel'],
        'aliases': ['barrack', 'tom barrack', 'thomas barrack', 'باراك', 'ברק'],
        'expected_posture': ('Speaks as the administration\'s regional voice; routinely '
                             'frames US involvement as brokering and de-escalation.'),
        'posture_basis': 'Institutional role as special envoy; on-record public statements.',
        'informative_deviation': ('Public criticism of ISRAELI action. Barrack described the '
                                  '18 Aug 2026 Abu al-Duhur strike as an unnecessary escalation '
                                  'that does not advance regional stability -- criticism from '
                                  'the striking party\'s own principal ally, which is costly and '
                                  'therefore carries more information than adversary '
                                  'condemnation of the same act.'),
        'subjects': ['israel', 'turkey', 'syria', 'lebanon'],
    },

    'issa': {
        'signal_mode': 'valence',
        'display': 'Amb. Michel Issa',
        'role': 'US Ambassador to Lebanon (credentials presented 17 Nov 2025)',
        'portfolio': ['lebanon'],
        'aliases': ['michel issa', 'ambassador issa', 'amb. issa', 'us ambassador to lebanon',
                    'ميشال عيسى', 'السفير عيسى'],
        'expected_posture': ('Presses Hizballah disarmament, financial pressure on the group, '
                             'and reinforcement of Lebanese state sovereignty. Told the Senate '
                             'Foreign Relations Committee that disarming Hizballah was "not a '
                             'choice but a necessity". Reported as functioning effectively as '
                             'the administration\'s special envoy on the Lebanon file.'),
        'posture_basis': 'Confirmation-hearing testimony; contemporaneous profile reporting.',
        'informative_deviation': ('(a) Public criticism of ISRAELI action in Lebanon -- off his '
                                  'baseline and therefore informative. (b) Softening on '
                                  'disarmament SEQUENCING, e.g. accepting aid or reconstruction '
                                  'ahead of clearance, which would signal a US position change '
                                  'on the Trilateral Framework gate order. (c) Public impatience '
                                  'with the LAF, which would signal that the clearance gate is '
                                  'being written off rather than waited on.'),
        'subjects': ['israel', 'hezbollah', 'lebanon', 'laf'],
    },

    'huckabee': {
        'signal_mode': 'valence',
        'display': 'Amb. Mike Huckabee',
        'role': 'US Ambassador to Israel',
        'portfolio': ['israel', 'west_bank'],
        'aliases': ['huckabee', 'mike huckabee', 'ambassador huckabee',
                    'هاكابي', 'האקבי'],
        'expected_posture': ('The most publicly settlement-sympathetic US voice in the region. '
                             'Has on the record preferred "Judea and Samaria" to "West Bank" '
                             'and questioned the framing of the territory as occupied. Speaks '
                             'to an evangelical constituency and does not always track '
                             'administration policy.'),
        'posture_basis': ('His own public statements and interviews. This records the public '
                          'record, not an inference about private belief.'),
        'informative_deviation': ('CRITICISM OF ISRAEL OR OF SETTLERS. This is the highest-value '
                                  'deviation available in this registry. Criticism of settler '
                                  'violence is abundant and costless from most sources; from the '
                                  'US voice most identified with the settlement movement it is '
                                  'costly, and it has historically indicated that an incident '
                                  'has passed a threshold his own constituency will not defend. '
                                  'The signal is the SPEAKER, not the sentiment.'),
        'subjects': ['israel', 'settlers', 'west_bank', 'palestinians'],
    },

    'ortagus': {
        'signal_mode': 'valence',
        'display': 'Morgan Ortagus',
        'role': 'US envoy, Lebanon file / ceasefire mechanism',
        'portfolio': ['lebanon', 'israel'],
        'aliases': ['morgan ortagus', 'ortagus', 'أورتاغوس'],
        'expected_posture': ('Works the Lebanon file alongside Amb. Issa, including contacts '
                             'with the Israeli side and participation in ceasefire-mechanism '
                             'meetings.'),
        'posture_basis': 'Contemporaneous reporting on the Lebanon ceasefire mechanism.',
        'informative_deviation': ('Public statements on mechanism failure or on Israeli '
                                  'non-compliance, either of which would indicate the ceasefire '
                                  'mechanism is being characterised as broken by a participant '
                                  'rather than by an observer.'),
        'subjects': ['israel', 'lebanon', 'hezbollah'],
    },

    # ── PRINCIPALS: mode='presence' ──
    'kushner': {
        'signal_mode': 'presence',
        'display': 'Jared Kushner',
        'role': 'Principal-level actor on the Gaza file; unveiled the "New Gaza" master plan (early 2026)',
        'portfolio': ['gaza', 'israel', 'gulf'],
        'aliases': ['jared kushner', 'kushner'],
        'expected_posture': ('Speaks rarely and at decision points rather than routinely. '
                             'Associated with the reconstruction-and-investment framing of the '
                             'Gaza file.'),
        'posture_basis': 'Contemporaneous reporting on the Board of Peace and the Gaza plan.',
        'informative_deviation': ('PRESENCE, not valence. A principal who speaks rarely is '
                                  'signalling by speaking at all -- it usually indicates a '
                                  'decision point has been reached or a track is being '
                                  'personally reactivated. What he says matters less than that '
                                  'he chose this moment to say it.'),
        'subjects': ['gaza', 'israel', 'palestinians'],
    },

    'witkoff': {
        'signal_mode': 'presence',
        'display': 'Steve Witkoff',
        'role': 'US Special Envoy to the Middle East',
        'portfolio': ['israel', 'gaza', 'gulf', 'iran'],
        'aliases': ['steve witkoff', 'witkoff', 'ويتكوف', 'וויטקוף'],
        'expected_posture': ('Speaks less frequently than any other voice in this registry, '
                             'and typically only when a track is being personally worked. '
                             'Reported at appointment as handling the Israel side directly, '
                             'with Boulos as point-man to Arab countries.'),
        'posture_basis': 'Appointment reporting (Times of Israel, Dec 2024); subsequent coverage of his envoy role.',
        'informative_deviation': ('PRESENCE, and the highest-scarcity presence signal here. '
                                  'Witkoff speaks less than Kushner, so a public surfacing is '
                                  'correspondingly more likely to mark a live decision point '
                                  'rather than routine engagement. He typically works in tandem '
                                  'with Kushner -- see PRINCIPAL_PAIRINGS, where co-presence is '
                                  'scored higher than either alone.'),
        'subjects': ['israel', 'gaza', 'iran', 'palestinians'],
    },

    'boulos': {
        'signal_mode': 'presence',
        'display': 'Massad Boulos',
        'role': 'US Senior Advisor for Arab and African Affairs (since Jan 2025); also Senior Advisor for Africa, Dept. of State',
        'portfolio': ['lebanon', 'gaza', 'gulf', 'africa'],
        'aliases': ['massad boulos', 'boulos', 'مسعد بولس'],
        'expected_posture': ('Lebanese-born; reported at appointment as the administration\'s '
                             'point-man to Arab countries, with Witkoff handling the Israel '
                             'side. Portfolio spans Arab affairs and Africa.'),
        'posture_basis': 'Appointment reporting (Times of Israel, Al Jazeera, CBS, Dec 2024); official role listings.',
        'informative_deviation': ('PRESENCE on the LEBANON file specifically. Boulos is '
                                  'Lebanese-born and family-connected, which makes him a '
                                  'plausible back-channel rather than a declaratory voice. His '
                                  'surfacing publicly on Lebanon is therefore more likely to '
                                  'indicate that a channel has become official than that a '
                                  'position has changed. Treat as a channel-state signal.'),
        'subjects': ['lebanon', 'gaza', 'hezbollah', 'palestinians'],
    },
}

# Valence vocabulary. Deliberately plain: we are detecting whether a named
# speaker was reported criticising or supporting, not performing sentiment
# analysis on the whole article.
CRITICAL_MARKERS = [
    'criticized', 'criticised', 'condemned', 'rebuked', 'scolded', 'warned against',
    'expressed concern', 'deeply concerned', 'unacceptable', 'unnecessary escalation',
    'does not advance', 'called on israel to', 'urged israel to', 'pressed israel',
    'disappointed', 'troubling', 'must stop', 'called it wrong', 'denounced',
    'انتقد', 'أدان', 'حذر',
    'מתח ביקורת', 'גינה',
]
SUPPORTIVE_MARKERS = [
    'praised', 'welcomed', 'backed', 'defended', 'endorsed', 'expressed support',
    'stood by', 'commended', 'right to defend', 'fully supports', 'applauded',
    'أشاد', 'دعم',
    'שיבח', 'תמך',
]

SUBJECT_MARKERS = {
    'israel':       ['israel', 'israeli', 'idf', 'netanyahu', 'إسرائيل', 'ישראל'],
    'settlers':     ['settler', 'settlers', 'outpost', 'settlement violence',
                     'مستوطن', 'מתנחלים'],
    'west_bank':    ['west bank', 'judea and samaria', 'area c', 'الضفة الغربية', 'הגדה'],
    'hezbollah':    ['hezbollah', 'hizballah', 'حزب الله', 'חיזבאללה'],
    'lebanon':      ['lebanon', 'lebanese', 'لبنان', 'לבנון'],
    'laf':          ['lebanese army', 'laf', 'الجيش اللبناني'],
    'turkey':       ['turkey', 'turkish', 'ankara', 'تركيا', 'טורקיה'],
    'syria':        ['syria', 'syrian', 'damascus', 'سوريا', 'סוריה'],
    'palestinians': ['palestinian', 'palestinians', 'فلسطين', 'פלסטינים'],
}

# PRINCIPAL PAIRINGS. Two rare speakers surfacing in the SAME cycle is not two
# independent signals -- it is one stronger signal. Witkoff and Kushner work the
# Gaza and Israel tracks in tandem, so their co-presence indicates a track being
# worked at principal level rather than either man commenting in passing.
# Scored as its own finding so it cannot be lost in a list of individual hits.
PRINCIPAL_PAIRINGS = {
    ('kushner', 'witkoff'): ('Kushner and Witkoff surfacing in the same cycle is the '
                             'principal-level pairing on the Gaza and Israel tracks. Both '
                             'speak rarely; both speaking at once is more consistent with an '
                             'active negotiation than with commentary.'),
    ('witkoff', 'boulos'):  ('Witkoff and Boulos together spans the reported division of '
                             'labour -- Israel side and Arab side -- which is the '
                             'configuration associated with a two-sided track rather than a '
                             'one-sided push.'),
    ('kushner', 'boulos'):  ('Kushner and Boulos together indicates the reconstruction and '
                             'Arab-outreach tracks being worked concurrently.'),
}

# Deviations worth flagging, by voice and subject. Keyed (voice, subject, valence).
# Presence here means: this combination is OFF that speaker's baseline.
HIGH_SIGNAL_DEVIATIONS = {
    ('huckabee', 'israel', 'critical'):   'highest',
    ('huckabee', 'settlers', 'critical'): 'highest',
    ('huckabee', 'west_bank', 'critical'): 'high',
    ('barrack', 'israel', 'critical'):    'high',
    ('issa', 'israel', 'critical'):       'high',
    ('ortagus', 'israel', 'critical'):    'high',
    ('issa', 'laf', 'critical'):          'moderate',
    ('issa', 'hezbollah', 'supportive'):  'highest',   # would be extraordinary
}


def _sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text or '') if s.strip()]


def detect_voice_signals(articles, voices=None):
    """Score US envoy statements against each speaker's own established posture.

    Valence is scored per SENTENCE, not per article: an article can quote a
    speaker praising one party and criticising another, and article-level
    scoring would collapse those into a single meaningless reading.
    """
    registry = {k: v for k, v in US_VOICE_REGISTRY.items()
                if (voices is None or k in voices)}
    results, deviations = {}, []

    for vid, spec in registry.items():
        mode = spec.get('signal_mode', 'valence')
        counts = {'mentions': 0, 'critical': {}, 'supportive': {}, 'mode': mode}
        quotes = []
        for a in (articles or []):
            blob = ((a.get('title') or '') + '. ' + (a.get('description') or ''))
            low = blob.lower()
            if not any(al in low for al in spec['aliases']):
                continue
            counts['mentions'] += 1
            for sent in _sentences(blob):
                sl = sent.lower()
                if not any(al in sl for al in spec['aliases']):
                    continue
                crit = any(m in sl for m in CRITICAL_MARKERS)
                supp = any(m in sl for m in SUPPORTIVE_MARKERS)
                if not (crit or supp):
                    continue
                for subj in spec['subjects']:
                    if any(m in sl for m in SUBJECT_MARKERS.get(subj, [])):
                        bucket = 'critical' if crit else 'supportive'
                        counts[bucket][subj] = counts[bucket].get(subj, 0) + 1
                        tier = HIGH_SIGNAL_DEVIATIONS.get((vid, subj, bucket))
                        if tier:
                            deviations.append({
                                'voice': vid,
                                'display': spec['display'],
                                'subject': subj,
                                'valence': bucket,
                                'tier': tier,
                                'quote': sent[:220],
                                'why': spec['informative_deviation'],
                                'expected_posture': spec['expected_posture'],
                                'posture_basis': spec['posture_basis'],
                                'url': a.get('url', ''),
                            })
                        quotes.append({'subject': subj, 'valence': bucket, 'text': sent[:180]})
        # PRESENCE MODE: a rare speaker surfacing at all is the finding. There is
        # no dense baseline to depart from, so waiting for a valence deviation
        # would mean waiting forever and missing the signal.
        if mode == 'presence' and counts['mentions'] > 0:
            deviations.append({
                'voice': vid,
                'display': spec['display'],
                'subject': 'presence',
                'valence': 'spoke',
                'tier': 'high',
                'quote': (quotes[0]['text'] if quotes else ''),
                'why': spec['informative_deviation'],
                'expected_posture': spec['expected_posture'],
                'posture_basis': spec['posture_basis'],
                'mentions': counts['mentions'],
                'url': '',
            })

        counts['quotes'] = quotes[:4]
        results[vid] = counts

    # Co-presence of principals: one stronger signal, not two independent ones.
    _present = {v for v, c in results.items()
                if c.get('mode') == 'presence' and c.get('mentions', 0) > 0}
    pairings = []
    for pair, why in PRINCIPAL_PAIRINGS.items():
        if set(pair).issubset(_present):
            pairings.append({'pair': list(pair), 'why': why})
            deviations.append({
                'voice': '+'.join(pair),
                'display': ' and '.join(US_VOICE_REGISTRY[v]['display'] for v in pair),
                'subject': 'co-presence',
                'valence': 'paired',
                'tier': 'highest',
                'quote': '',
                'why': why,
                'expected_posture': 'Both speak rarely; simultaneous surfacing is the finding.',
                'posture_basis': 'Reported division of labour between these principals.',
                'url': '',
            })

    # Rank: 'highest' before 'high' before 'moderate'.
    order = {'highest': 0, 'high': 1, 'moderate': 2}
    deviations.sort(key=lambda d: order.get(d['tier'], 9))

    if deviations:
        top = deviations[0]
        if top['valence'] == 'paired':
            headline = ('%s surfaced in the same cycle — principal-level pairing'
                        % top['display'])
        elif top['valence'] == 'spoke':
            headline = ('%s surfaced publicly (%d mention(s)) — presence signal'
                        % (top['display'], top.get('mentions', 1)))
        else:
            headline = ('%s spoke off baseline: %s toward %s'
                        % (top['display'], top['valence'], top['subject'].replace('_', ' ')))
        note = ('SIGNAL VALUE IS INVERSELY PROPORTIONAL TO EXPECTEDNESS. This is flagged '
                'because of WHO said it, not what was said. %s Expected posture on the '
                'public record: %s (%s) '
                % (top['why'], top['expected_posture'], top['posture_basis']))
    else:
        headline = 'No US envoy statements off baseline this cycle'
        note = ('Envoy statements consistent with each speaker\'s established public posture '
                'carry little information and are counted but not flagged. Absence of a '
                'deviation is NOT a finding about US policy -- it is the ordinary condition. ')

    note += ('Postures record PUBLICLY STATED positions and institutional role, not inferences '
             'about private belief. This is a CONVERGENCE indicator, NOT a probability of '
             'action.')

    return {
        'voices': results,
        'deviations': deviations[:5],
        'deviation_count': len(deviations),
        'principal_pairings': pairings,
        'headline': headline,
        'note': note,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'version': __version__,
    }


def tempo_streams(result):
    """Flatten to tempo_baseline streams: one per voice, counting deviations.

    mode='tape' territory -- an envoy does not announce that he has departed
    from his own baseline, so there is no claiming actor to fall silent.
    """
    out = {}
    for vid in US_VOICE_REGISTRY:
        out['%s_mentions' % vid] = (result.get('voices', {}).get(vid, {}) or {}).get('mentions', 0)
    out['deviations'] = result.get('deviation_count', 0)
    return out
